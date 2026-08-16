import type { INodeType, INodeTypeDescription } from 'n8n-workflow';
import { NodeConnectionTypes } from 'n8n-workflow';

// Declarative node — every operation is a `routing` block mapped directly onto one of
// Threadly's public REST endpoints (backend/app/api/public/v1/content.py). No execute()
// needed: these are thin, single-request wrappers, and n8n's own HTTP-request-node engine
// (driven by the `routing` property below) handles auth, pagination display, and error
// surfacing identically to how it would for any other declarative-style node.
export class Threadly implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Threadly',
		name: 'threadly',
		icon: { light: 'file:threadly.svg', dark: 'file:threadly.dark.svg' },
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"] + ": " + $parameter["resource"]}}',
		description: 'Find X conversations and review AI-drafted replies from Threadly',
		defaults: {
			name: 'Threadly',
		},
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		usableAsTool: true,
		credentials: [
			{
				name: 'threadlyApi',
				required: true,
			},
		],
		requestDefaults: {
			baseURL: '={{$credentials.baseUrl}}',
			headers: {
				Accept: 'application/json',
			},
		},
		properties: [
			{
				displayName: 'Resource',
				name: 'resource',
				type: 'options',
				noDataExpression: true,
				options: [
					{ name: 'Conversation', value: 'conversation' },
					{ name: 'Draft', value: 'draft' },
					{ name: 'Reply', value: 'reply' },
				],
				default: 'draft',
			},

			// --- Conversation ---
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: { show: { resource: ['conversation'] } },
				options: [
					{
						name: 'List',
						value: 'list',
						description: 'List X conversations Threadly has discovered',
						action: 'List conversations',
						routing: {
							request: {
								method: 'GET',
								url: '/public/v1/conversations',
								qs: {
									tag: '={{$parameter["tag"] || undefined}}',
									limit: '={{$parameter["limit"]}}',
									offset: '={{$parameter["offset"]}}',
								},
							},
						},
					},
				],
				default: 'list',
			},
			{
				displayName: 'Tag',
				name: 'tag',
				type: 'string',
				default: '',
				description: 'Filter to conversations with this tag',
				displayOptions: { show: { resource: ['conversation'], operation: ['list'] } },
			},

			// --- Draft ---
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: { show: { resource: ['draft'] } },
				options: [
					{
						name: 'List',
						value: 'list',
						description: 'List drafts awaiting (or already given) a decision',
						action: 'List drafts',
						routing: {
							request: {
								method: 'GET',
								url: '/public/v1/drafts',
								qs: {
									status: '={{$parameter["status"]}}',
									limit: '={{$parameter["limit"]}}',
									offset: '={{$parameter["offset"]}}',
								},
							},
						},
					},
					{
						name: 'Approve',
						value: 'approve',
						description: 'Approve a draft — posts it (except X/Twitter, which requires a manual post)',
						action: 'Approve a draft',
						routing: {
							request: {
								method: 'POST',
								url: '=/public/v1/drafts/{{$parameter["draftId"]}}/approve',
							},
						},
					},
					{
						name: 'Reject',
						value: 'reject',
						description: 'Reject a draft',
						action: 'Reject a draft',
						routing: {
							request: {
								method: 'POST',
								url: '=/public/v1/drafts/{{$parameter["draftId"]}}/reject',
								body: {
									reason: '={{$parameter["reason"]}}',
								},
							},
						},
					},
				],
				default: 'list',
			},
			{
				displayName: 'Status',
				name: 'status',
				type: 'options',
				default: 'pending_review',
				description: 'Which drafts to list, by their current status',
				options: [
					{ name: 'Approved', value: 'approved' },
					{ name: 'Archived', value: 'archived' },
					{ name: 'Draft', value: 'draft' },
					{ name: 'Pending Review', value: 'pending_review' },
					{ name: 'Published', value: 'published' },
					{ name: 'Rejected', value: 'rejected' },
				],
				displayOptions: { show: { resource: ['draft'], operation: ['list'] } },
			},
			{
				displayName: 'Draft ID',
				name: 'draftId',
				type: 'string',
				default: '',
				required: true,
				description: 'The content item ID to approve or reject — from a previous List Drafts call, or the conversation.discovered trigger',
				displayOptions: { show: { resource: ['draft'], operation: ['approve', 'reject'] } },
			},
			{
				displayName: 'Reason',
				name: 'reason',
				type: 'string',
				default: '',
				required: true,
				description: 'Why this draft is being rejected',
				displayOptions: { show: { resource: ['draft'], operation: ['reject'] } },
			},

			// --- Reply ---
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				displayOptions: { show: { resource: ['reply'] } },
				options: [
					{
						name: 'List',
						value: 'list',
						description: 'List replies that have already been posted',
						action: 'List replies',
						routing: {
							request: {
								method: 'GET',
								url: '/public/v1/replies',
								qs: {
									limit: '={{$parameter["limit"]}}',
									offset: '={{$parameter["offset"]}}',
								},
							},
						},
					},
				],
				default: 'list',
			},

			// --- Shared pagination, for every List operation ---
			{
				displayName: 'Limit',
				name: 'limit',
				type: 'number',
				default: 50,
				typeOptions: { minValue: 1, maxValue: 200 },
				description: 'Max number of results to return',
				displayOptions: { show: { operation: ['list'] } },
			},
			{
				displayName: 'Offset',
				name: 'offset',
				type: 'number',
				default: 0,
				typeOptions: { minValue: 0 },
				description: 'Number of results to skip, for paging through a large list',
				displayOptions: { show: { operation: ['list'] } },
			},
		],
	};
}
