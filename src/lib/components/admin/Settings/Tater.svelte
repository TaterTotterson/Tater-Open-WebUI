<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getBackendConfig, getModels } from '$lib/apis';
	import {
		getTaterProfile,
		updateTaterProfile,
		verifyTaterProfile,
		type TaterProfile,
		type TaterProfileInput,
		type TaterProfileVerification
	} from '$lib/apis/tater';
	import { config, models } from '$lib/stores';

	const dispatch = createEventDispatcher();
	const inputClass =
		'w-full h-8 rounded-lg border border-gray-100/50 bg-gray-50/40 px-2.5 text-xs text-gray-700 outline-hidden transition-colors placeholder:text-gray-300 focus:border-blue-400 dark:border-white/[0.04] dark:bg-white/[0.03] dark:text-gray-300 dark:placeholder:text-gray-700 dark:focus:border-blue-500';

	let profile: TaterProfile | null = null;
	let apiBaseUrl = '';
	let apiKey = '';
	let apiKeyChanged = false;
	let baseModel = 'tater/base';
	let hydraModel = 'tater/hydra';
	let contextWindow = 32768;
	let saving = false;
	let verifying = false;
	let verification: TaterProfileVerification | null = null;

	const loadProfile = async () => {
		profile = await getTaterProfile(localStorage.token);
		apiBaseUrl = profile.api_base_url;
		baseModel = profile.base_model;
		hydraModel = profile.hydra_model;
		contextWindow = profile.context_window;
		apiKey = '';
		apiKeyChanged = false;
	};

	const formValue = (): TaterProfileInput => ({
		api_base_url: apiBaseUrl,
		api_key: apiKeyChanged ? apiKey : null,
		base_model: baseModel,
		hydra_model: hydraModel,
		context_window: Math.max(4096, Math.floor(Number(contextWindow) || 32768))
	});

	const refreshModels = async () => {
		await models.set(await getModels(localStorage.token, false, true));
	};

	const save = async () => {
		if (saving) return;
		saving = true;
		verification = null;

		try {
			profile = await updateTaterProfile(localStorage.token, formValue());
			apiBaseUrl = profile.api_base_url;
			baseModel = profile.base_model;
			hydraModel = profile.hydra_model;
			contextWindow = profile.context_window;
			apiKey = '';
			apiKeyChanged = false;
			await refreshModels();
			await config.set(await getBackendConfig());
			toast.success('Tater connection saved');
			dispatch('save');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			saving = false;
		}
	};

	const verify = async () => {
		if (verifying) return;
		verifying = true;
		verification = null;

		try {
			verification = await verifyTaterProfile(localStorage.token, formValue());
			if (!verification.base_model_available || !verification.hydra_model_available) {
				toast.warning('Connected, but one or more configured Tater models were not advertised');
			} else {
				toast.success('Connected to Tater');
			}
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			verifying = false;
		}
	};

	onMount(async () => {
		try {
			await loadProfile();
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		}
	});
</script>

<form class="flex h-full flex-col justify-between text-sm" on:submit|preventDefault={save}>
	<div class="flex-1 min-h-0 overflow-y-auto scrollbar-hover pr-1.5">
		<div class="flex items-center gap-4">
			<img
				src="/static/tater-open-webui-logo.png"
				alt="Tater mascot leaning on the Open WebUI logo"
				class="size-16 object-contain"
			/>
			<div>
				<h2 class="text-sm font-medium text-gray-900 dark:text-white">Tater connection</h2>
				<p class="mt-1 max-w-2xl text-xs text-gray-500 dark:text-gray-400">
					Tater Open WebUI uses this single OpenAI-compatible endpoint for normal chat and
					Tater tool delegation. Local terminal and filesystem tools run on this Tater Open
					WebUI host.
				</p>
			</div>
		</div>

		{#if profile === null}
			<div class="mt-6 text-xs text-gray-400">Loading Tater settings…</div>
		{:else}
			<div class="mt-6 max-w-2xl space-y-5">
				<label class="block">
					<span class="text-xs text-gray-600 dark:text-gray-400">Tater API URL</span>
					<input
						class="mt-1 {inputClass}"
						type="text"
						bind:value={apiBaseUrl}
						placeholder="http://localhost:8501/v1"
						required
					/>
					<span class="mt-1 block text-[0.6875rem] text-gray-400 dark:text-gray-600">
						Include the OpenAI-compatible API prefix, normally <code>/v1</code>.
					</span>
				</label>

				<label class="block">
					<span class="text-xs text-gray-600 dark:text-gray-400">API key</span>
					<input
						class="mt-1 {inputClass}"
						type="password"
						bind:value={apiKey}
						on:input={() => (apiKeyChanged = true)}
						placeholder={profile.api_key_configured
							? 'Saved — enter a value only to replace it'
							: 'Optional if Tater does not require authentication'}
						autocomplete="new-password"
					/>
					{#if profile.api_key_configured && !apiKeyChanged}
						<button
							class="mt-1 text-[0.6875rem] text-gray-400 hover:text-red-600 dark:text-gray-600 dark:hover:text-red-400"
							type="button"
							on:click={() => {
								apiKey = '';
								apiKeyChanged = true;
							}}
						>
							Clear the saved key on next save
						</button>
					{/if}
				</label>

				<div class="grid gap-4 sm:grid-cols-2">
					<label class="block">
						<span class="text-xs text-gray-600 dark:text-gray-400">Normal chat model</span>
						<input class="mt-1 {inputClass}" bind:value={baseModel} required />
						<span class="mt-1 block text-[0.6875rem] text-gray-400 dark:text-gray-600">
							Used for ordinary responses and local computer work.
						</span>
					</label>

					<label class="block">
						<span class="text-xs text-gray-600 dark:text-gray-400">Tater tool model</span>
						<input class="mt-1 {inputClass}" bind:value={hydraModel} required />
						<span class="mt-1 block text-[0.6875rem] text-gray-400 dark:text-gray-600">
							Reserved for Hydra delegation and hidden from the ordinary model picker.
						</span>
					</label>
				</div>

				<label class="block">
					<span class="text-xs text-gray-600 dark:text-gray-400">Model context window</span>
					<input
						class="mt-1 {inputClass}"
						type="number"
						min="4096"
						max="2000000"
						step="1024"
						bind:value={contextWindow}
						required
					/>
					<span class="mt-1 block text-[0.6875rem] text-gray-400 dark:text-gray-600">
						Set this to the context length configured on the server. Tater Open WebUI will
						compact at 80% and reserve the remainder for tool instructions and the answer.
					</span>
				</label>

				{#if verification}
					<div
						class="rounded-lg border border-gray-100 bg-gray-50/60 p-3 text-xs dark:border-white/[0.06] dark:bg-white/[0.03]"
					>
						<div class="font-medium text-gray-700 dark:text-gray-200">Connection verified</div>
						<div class="mt-1 text-gray-500 dark:text-gray-400">
							Normal model: {verification.base_model_available ? 'available' : 'not advertised'} · Hydra:
							{verification.hydra_model_available ? 'available' : 'not advertised'}
						</div>
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<div class="mt-4 flex justify-end gap-2">
		<button
			class="rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
			type="button"
			disabled={profile === null || verifying || saving}
			on:click={verify}
		>
			{verifying ? 'Testing…' : 'Test connection'}
		</button>
		<button
			class="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-50 dark:bg-white dark:text-black dark:hover:bg-gray-200"
			type="submit"
			disabled={profile === null || saving || verifying}
		>
			{saving ? 'Saving…' : 'Save'}
		</button>
	</div>
</form>
