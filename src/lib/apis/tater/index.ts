import { WEBUI_API_BASE_URL } from '$lib/constants';
import { getErrorMessage } from '$lib/apis/openai';

export type TaterProfile = {
	api_base_url: string;
	api_key_configured: boolean;
	base_model: string;
	hydra_model: string;
	context_window: number;
	linked: boolean;
	hub_url: string;
	hub_name: string;
	node_id: string;
	connected_at: number;
	capabilities: Record<string, boolean>;
	speech: Record<string, string | boolean>;
};

export type TaterProfileInput = {
	context_window: number;
};

export type TaterProfileVerification = {
	connected: boolean;
	base_model_available: boolean;
	hydra_model_available: boolean;
	models: string[];
};

export type TaterTask = {
	id: string;
	title: string;
	status:
		| 'queued'
		| 'running'
		| 'cancelling'
		| 'completed'
		| 'failed'
		| 'cancelled'
		| 'interrupted'
		| 'unknown';
	activity: string;
	progress_events: {
		at: number;
		kind: string;
		message: string;
	}[];
	result_summary: string;
	capabilities: ('terminal' | 'hydra')[];
	parent_chat_id: string | null;
	created_at: number;
	updated_at: number;
	started_at: number | null;
	finished_at: number | null;
};

export type TaterTaskHistoryItem = TaterTask & {
	parent_chat_title: string | null;
	prompt_preview: string;
	output_preview: string;
};

export type TaterTaskDetail = TaterTask & {
	prompt: string;
	output: string;
};

const request = async <T>(path: string, token: string, options: RequestInit = {}): Promise<T> => {
	const response = await fetch(`${WEBUI_API_BASE_URL}/tater${path}`, {
		...options,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	});

	if (!response.ok) {
		let error: unknown;
		try {
			error = await response.json();
		} catch {
			error = await response.text();
		}
		throw new Error(getErrorMessage(error));
	}

	return response.json();
};

export const getTaterProfile = (token: string): Promise<TaterProfile> => request('/config', token);

export const updateTaterProfile = (
	token: string,
	profile: TaterProfileInput
): Promise<TaterProfile> =>
	request('/config', token, {
		method: 'POST',
		body: JSON.stringify(profile)
	});

export const linkTater = (
	token: string,
	hubUrl: string,
	pairingCode: string
): Promise<TaterProfile> =>
	request('/link', token, {
		method: 'POST',
		body: JSON.stringify({ hub_url: hubUrl, pairing_code: pairingCode })
	});

export const verifyTaterLink = (token: string): Promise<TaterProfileVerification> =>
	request('/link/verify', token, { method: 'POST' });

export const unlinkTater = (token: string): Promise<TaterProfile> =>
	request('/link', token, { method: 'DELETE' });

export const getTaterTasks = (token: string): Promise<TaterTask[]> => request('/tasks', token);

export const getTaterTaskHistory = (
	token: string,
	limit = 50,
	offset = 0
): Promise<TaterTaskHistoryItem[]> =>
	request(
		`/tasks/history?limit=${encodeURIComponent(String(limit))}&offset=${encodeURIComponent(String(offset))}`,
		token
	);

export const getTaterTask = (token: string, taskId: string): Promise<TaterTaskDetail> =>
	request(`/tasks/${encodeURIComponent(taskId)}`, token);

export const cancelTaterTask = (token: string, taskId: string): Promise<TaterTask> =>
	request(`/tasks/${encodeURIComponent(taskId)}`, token, { method: 'DELETE' });
