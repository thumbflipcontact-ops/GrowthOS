import type {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class ThreadlyApi implements ICredentialType {
	name = 'threadlyApi';

	displayName = 'Threadly API';

	icon = 'file:../nodes/Threadly/threadly.svg' as const;

	documentationUrl = 'https://github.com/thumbflipcontact-ops/GrowthOS/blob/main/docs/api/PUBLIC_API.md';

	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			required: true,
			description:
				'A Threadly project API key, created from Settings → API Keys in your Threadly dashboard. Starts with "thr_".',
		},
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'https://growthos-production-d600.up.railway.app',
			required: true,
			description: 'The base URL of your Threadly deployment. Leave as default unless self-hosting.',
		},
	];

	// Applied to every request this credential authenticates — see
	// backend/app/api/deps.py's require_api_key_project, which expects exactly this header.
	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				Authorization: '=Bearer {{$credentials.apiKey}}',
			},
		},
	};

	// The cheapest real endpoint that proves a key actually works — see
	// backend/app/api/public/v1/content.py's list_conversations.
	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl}}',
			url: '/public/v1/conversations',
		},
	};
}
