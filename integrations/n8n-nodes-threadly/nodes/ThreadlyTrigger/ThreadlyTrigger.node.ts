import { createHmac, timingSafeEqual } from 'crypto';
import type {
	IHookFunctions,
	IWebhookFunctions,
	IWebhookResponseData,
	INodeType,
	INodeTypeDescription,
} from 'n8n-workflow';
import { NodeConnectionTypes } from 'n8n-workflow';

// Modeled directly on n8n core's own GithubTrigger.node.ts — same webhookMethods lifecycle
// (checkExists/create/delete) registering/deregistering a webhook with an external API on
// workflow activate/deactivate, and the same HMAC-SHA256-over-the-raw-body verification
// pattern GitHub/Zendesk/Linear's trigger nodes use, adapted to Threadly's own signature
// scheme (see backend/app/core/webhooks/signing.py and dispatcher.py — same
// "sha256=<hex hmac>" header format, same secret-per-subscription model).

async function threadlyRequest(
	this: IHookFunctions | IWebhookFunctions,
	method: 'GET' | 'POST' | 'DELETE',
	path: string,
	body?: object,
) {
	const credentials = await this.getCredentials('threadlyApi');
	return this.helpers.httpRequestWithAuthentication.call(this, 'threadlyApi', {
		method,
		url: `${credentials.baseUrl}${path}`,
		body,
		json: true,
	});
}

function verifySignature(this: IWebhookFunctions): boolean {
	const webhookData = this.getWorkflowStaticData('node');
	const secret = webhookData.secret as string | undefined;
	if (!secret) {
		return false;
	}

	const req = this.getRequestObject();
	const signatureHeader = req.headers['x-threadly-signature'] as string | undefined;
	if (!signatureHeader || !signatureHeader.startsWith('sha256=')) {
		return false;
	}
	const providedSignature = signatureHeader.slice('sha256='.length);

	if (!req.rawBody) {
		return false;
	}

	try {
		const hmac = createHmac('sha256', secret);
		hmac.update(Buffer.isBuffer(req.rawBody) ? req.rawBody : String(req.rawBody));
		const computedBuffer = Buffer.from(hmac.digest('hex'), 'utf8');
		const providedBuffer = Buffer.from(providedSignature, 'utf8');
		if (computedBuffer.length !== providedBuffer.length) {
			return false;
		}
		return timingSafeEqual(computedBuffer, providedBuffer);
	} catch {
		return false;
	}
}

export class ThreadlyTrigger implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Threadly Trigger',
		name: 'threadlyTrigger',
		icon: { light: 'file:../Threadly/threadly.svg', dark: 'file:../Threadly/threadly.dark.svg' },
		group: ['trigger'],
		version: 1,
		subtitle: '={{"conversation.discovered"}}',
		description: 'Starts the workflow when Threadly discovers a new X conversation',
		defaults: {
			name: 'Threadly Trigger',
		},
		inputs: [],
		outputs: [NodeConnectionTypes.Main],
		usableAsTool: true,
		credentials: [
			{
				name: 'threadlyApi',
				required: true,
			},
		],
		webhooks: [
			{
				name: 'default',
				httpMethod: 'POST',
				responseMode: 'onReceived',
				path: 'webhook',
			},
		],
		properties: [
			{
				displayName: 'Only one event is currently supported: a new conversation Threadly discovered on X.',
				name: 'notice',
				type: 'notice',
				default: '',
			},
		],
	};

	webhookMethods = {
		default: {
			// Confirms the subscription this node created is still active on Threadly's side —
			// n8n calls this before `create` on activation, so a manually-deleted subscription
			// (e.g. revoked from Threadly's own dashboard) gets correctly re-created rather than
			// silently assumed to still exist.
			async checkExists(this: IHookFunctions): Promise<boolean> {
				const webhookData = this.getWorkflowStaticData('node');
				const subscriptionId = webhookData.subscriptionId as string | undefined;
				if (!subscriptionId) {
					return false;
				}
				const subscriptions = (await threadlyRequest.call(
					this,
					'GET',
					'/public/v1/webhook-subscriptions',
				)) as Array<{ id: string; enabled: boolean }>;
				return subscriptions.some((s) => s.id === subscriptionId && s.enabled);
			},

			async create(this: IHookFunctions): Promise<boolean> {
				const webhookUrl = this.getNodeWebhookUrl('default');
				const response = (await threadlyRequest.call(this, 'POST', '/public/v1/webhook-subscriptions', {
					target_url: webhookUrl,
					event_types: ['conversation.discovered'],
				})) as { id: string; secret: string };

				const webhookData = this.getWorkflowStaticData('node');
				webhookData.subscriptionId = response.id;
				webhookData.secret = response.secret;
				return true;
			},

			async delete(this: IHookFunctions): Promise<boolean> {
				const webhookData = this.getWorkflowStaticData('node');
				const subscriptionId = webhookData.subscriptionId as string | undefined;
				if (subscriptionId) {
					try {
						await threadlyRequest.call(this, 'DELETE', `/public/v1/webhook-subscriptions/${subscriptionId}`);
					} catch (error) {
						// Already gone (e.g. revoked from the dashboard) — deactivation must still
						// succeed locally, same as GithubTrigger's own delete() tolerates a 404 —
						// but log it rather than swallow it silently, in case it's a real failure
						// (network error, auth revoked) rather than an expected 404.
						this.logger.warn('Threadly Trigger: failed to delete webhook subscription', {
							subscriptionId,
							error,
						});
					}
				}
				delete webhookData.subscriptionId;
				delete webhookData.secret;
				return true;
			},
		},
	};

	async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
		if (!verifySignature.call(this)) {
			const res = this.getResponseObject();
			res.status(401).send('Unauthorized').end();
			return { noWebhookResponse: true };
		}

		const body = this.getBodyData();
		return {
			workflowData: [this.helpers.returnJsonArray(body)],
		};
	}
}
