import { WEBUI_API_BASE_URL } from '$lib/constants';
import { getErrorMessage } from '$lib/apis/openai';

export type TaterProfile = {
	api_base_url: string;
	api_key_configured: boolean;
	base_model: string;
	hydra_model: string;
	context_window: number;
};

export type TaterProfileInput = {
	api_base_url: string;
	api_key: string | null;
	base_model: string;
	hydra_model: string;
	context_window: number;
};

export type TaterProfileVerification = {
	connected: boolean;
	base_model_available: boolean;
	hydra_model_available: boolean;
	models: string[];
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

export const verifyTaterProfile = (
	token: string,
	profile: TaterProfileInput
): Promise<TaterProfileVerification> =>
	request('/verify', token, {
		method: 'POST',
		body: JSON.stringify(profile)
	});
