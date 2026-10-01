<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getBackendConfig, getModels } from '$lib/apis';
	import {
		getTaterProfile,
		linkTater,
		unlinkTater,
		updateTaterProfile,
		verifyTaterLink,
		type TaterProfile,
		type TaterProfileVerification
	} from '$lib/apis/tater';
	import { config, models } from '$lib/stores';

	const dispatch = createEventDispatcher();

	let profile: TaterProfile | null = null;
	let hubUrl = '';
	let pairingCode = '';
	let contextWindow = 32768;
	let linking = false;
	let saving = false;
	let verifying = false;
	let disconnecting = false;
	let verification: TaterProfileVerification | null = null;

	const loadProfile = async () => {
		profile = await getTaterProfile(localStorage.token);
		hubUrl = profile.hub_url || profile.api_base_url.replace(/\/v1\/?$/, '');
		contextWindow = profile.context_window;
	};

	const refreshRuntime = async () => {
		await models.set(await getModels(localStorage.token, false, true));
		await config.set(await getBackendConfig());
	};

	const connect = async () => {
		if (linking) return;
		linking = true;
		verification = null;
		try {
			profile = await linkTater(localStorage.token, hubUrl, pairingCode);
			hubUrl = profile.hub_url;
			contextWindow = profile.context_window;
			pairingCode = '';
			await refreshRuntime();
			toast.success('Tater Open WebUI is linked to Tater');
			dispatch('save');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			linking = false;
		}
	};

	const saveWorkspace = async () => {
		if (!profile || saving) return;
		saving = true;
		try {
			profile = await updateTaterProfile(localStorage.token, {
				context_window: Math.max(4096, Math.floor(Number(contextWindow) || 32768))
			});
			contextWindow = profile.context_window;
			await refreshRuntime();
			toast.success('Tater Open WebUI settings saved');
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
			verification = await verifyTaterLink(localStorage.token);
			profile = await getTaterProfile(localStorage.token);
			if (verification.base_model_available && verification.hydra_model_available) {
				toast.success('Tater link is healthy');
			} else {
				toast.warning('Tater is connected, but a required model is unavailable');
			}
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			verifying = false;
		}
	};

	const disconnect = async () => {
		if (!profile || disconnecting) return;
		if (
			!window.confirm(
				'Disconnect Tater Open WebUI from this Tater? A new pairing code will be required.'
			)
		) {
			return;
		}
		disconnecting = true;
		try {
			profile = await unlinkTater(localStorage.token);
			verification = null;
			await refreshRuntime();
			toast.success('Tater Open WebUI disconnected');
			dispatch('save');
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			disconnecting = false;
		}
	};

	const capabilityReady = (name: string) => Boolean(profile?.capabilities?.[name]);

	onMount(async () => {
		try {
			await loadProfile();
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		}
	});
</script>

<div class="tater-setup">
	<section class="tater-hero">
		<div class="tater-glow tater-glow-one"></div>
		<div class="tater-glow tater-glow-two"></div>
		<div class="tater-brand">
			<div class="tater-logo-shell">
				<img src="/static/tater-open-webui-logo.png" alt="Tater Open WebUI" />
			</div>
			<div>
				<span class="tater-kicker">SPUDLINK WORKSPACE</span>
				<h2>Tater Open WebUI</h2>
				<p>
					One private link powers normal chat, Hydra tools, speech recognition, and Tater's voice.
					Coding, projects, tasks, and the terminal remain local to this workspace.
				</p>
			</div>
		</div>
		<div class:online={profile?.linked} class="tater-status-pill">
			<i></i>{profile?.linked ? `Linked to ${profile.hub_name || 'Tater'}` : 'Ready to pair'}
		</div>
	</section>

	{#if profile === null}
		<div class="tater-loading"><span></span>Loading Tater Open WebUI settings…</div>
	{:else if !profile.linked}
		<div class="tater-unlinked-grid">
			<section class="tater-card tater-connect-card">
				<header>
					<span class="tater-kicker">SECURE PAIRING</span>
					<h3>Connect this workspace</h3>
					<p>
						Create a “Tater Open WebUI” code from Tater's Spud Link settings, then enter it here.
					</p>
				</header>

				<label>
					<span>Tater URL</span>
					<input bind:value={hubUrl} type="text" placeholder="http://tater.local:8501" />
					<small>Use the address Tater Open WebUI can reach from its Docker container.</small>
				</label>
				<label>
					<span>One-time pairing code</span>
					<input
						bind:value={pairingCode}
						type="text"
						autocomplete="off"
						placeholder="SPUD-XXXXXX-XXXXXX"
					/>
				</label>

				<button
					class="tater-primary"
					type="button"
					disabled={linking || !hubUrl.trim() || !pairingCode.trim()}
					on:click={connect}
				>
					{linking ? 'Linking securely…' : 'Link Tater Open WebUI'}
				</button>
			</section>

			<section class="tater-card tater-route-card">
				<span class="tater-kicker">WHAT THE LINK ENABLES</span>
				<h3>One Tater, clear responsibilities</h3>
				<div class="route-list">
					<div>
						<i class="base"></i><span
							><strong>tater/base</strong><small
								>Conversation, planning, and the local coding loop</small
							></span
						>
					</div>
					<div>
						<i class="terminal"></i><span
							><strong>Local terminal</strong><small
								>Files and commands stay inside Tater Open WebUI</small
							></span
						>
					</div>
					<div>
						<i class="hydra"></i><span
							><strong>tater/hydra</strong><small
								>Image, audio, music, and video generation, home control, and other Tater tools</small
							></span
						>
					</div>
					<div>
						<i class="voice"></i><span
							><strong>Tater voice</strong><small
								>STT and TTS power microphone, playback, and voice mode</small
							></span
						>
					</div>
				</div>
			</section>
		</div>
	{:else}
		<div class="tater-linked-grid">
			<section class="tater-card tater-connection-card">
				<header class="card-heading">
					<div>
						<span class="tater-kicker">LIVE CONNECTION</span>
						<h3>{profile.hub_name || 'Tater'}</h3>
					</div>
					<span class="healthy"><i></i>Connected</span>
				</header>
				<div class="connection-address">{profile.hub_url}</div>
				<div class="capability-grid">
					<div class:ready={capabilityReady('normal_chat')}>
						<i></i><span>Normal chat<strong>tater/base</strong></span>
					</div>
					<div class:ready={capabilityReady('hydra')}>
						<i></i><span>Tater tools<strong>tater/hydra</strong></span>
					</div>
					<div class:ready={capabilityReady('stt')}>
						<i></i><span
							>Speech to text<strong>{profile.speech?.stt_backend || 'Tater STT'}</strong></span
						>
					</div>
					<div class:ready={capabilityReady('tts')}>
						<i></i><span
							>Text to speech<strong
								>{profile.speech?.tts_voice || profile.speech?.tts_model || 'Tater voice'}</strong
							></span
						>
					</div>
				</div>
				{#if verification}
					<div class="verification-result">
						<span>✓</span>
						<div>
							<strong>Connection verified</strong><small
								>Normal chat and Hydra are both available.</small
							>
						</div>
					</div>
				{/if}
				<div class="button-row">
					<button class="tater-secondary" type="button" disabled={verifying} on:click={verify}>
						{verifying ? 'Testing…' : 'Test connection'}
					</button>
					<button class="tater-danger" type="button" disabled={disconnecting} on:click={disconnect}>
						{disconnecting ? 'Disconnecting…' : 'Disconnect'}
					</button>
				</div>
			</section>

			<section class="tater-card tater-workspace-card">
				<header>
					<span class="tater-kicker">WORKSPACE MODEL</span>
					<h3>Built for long-running work</h3>
					<p>
						The linked models are intentionally fixed so no generic providers can replace Tater's
						routing.
					</p>
				</header>
				<div class="model-pair">
					<div>
						<span>NORMAL CHAT</span><strong>tater/base</strong><small
							>Ordinary responses, coding, and terminal decisions</small
						>
					</div>
					<div>
						<span>TATER TOOLS</span><strong>tater/hydra</strong><small
							>Hidden from the picker and called only when needed</small
						>
					</div>
				</div>
				<label class="context-field">
					<span>Model context window</span>
					<input bind:value={contextWindow} type="number" min="4096" max="2000000" step="1024" />
					<small
						>Tater Open WebUI compacts at 80%, leaving room for tools and the final answer.</small
					>
				</label>
				<button class="tater-primary" type="button" disabled={saving} on:click={saveWorkspace}>
					{saving ? 'Saving…' : 'Save workspace settings'}
				</button>
			</section>
		</div>
	{/if}
</div>

<style>
	.tater-setup {
		--tater-orange: #f28c28;
		--tater-orange-bright: #ffad45;
		--tater-purple: #7c5cff;
		--tater-green: #55d68b;
		display: flex;
		height: 100%;
		min-height: 0;
		flex-direction: column;
		gap: 1rem;
		overflow-y: auto;
		padding-right: 0.35rem;
	}

	.tater-hero,
	.tater-card {
		position: relative;
		overflow: hidden;
		border: 1px solid rgba(242, 140, 40, 0.18);
		background: linear-gradient(145deg, rgba(255, 250, 242, 0.96), rgba(255, 255, 255, 0.9));
		box-shadow: 0 18px 50px rgba(84, 42, 10, 0.06);
	}

	:global(.dark) .tater-hero,
	:global(.dark) .tater-card {
		border-color: rgba(255, 173, 69, 0.13);
		background: linear-gradient(145deg, rgba(37, 25, 20, 0.96), rgba(21, 19, 25, 0.94));
		box-shadow: 0 18px 55px rgba(0, 0, 0, 0.22);
	}

	.tater-hero {
		display: flex;
		min-height: 10.5rem;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		border-radius: 1.5rem;
		padding: 1.4rem 1.55rem;
	}
	.tater-brand {
		position: relative;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 1.2rem;
	}
	.tater-logo-shell {
		display: grid;
		width: 7.5rem;
		height: 7.5rem;
		flex: 0 0 auto;
		place-items: center;
		border-radius: 2rem;
		background: radial-gradient(
			circle at 35% 30%,
			rgba(255, 255, 255, 0.9),
			rgba(255, 173, 69, 0.15)
		);
	}
	.tater-logo-shell img {
		width: 7rem;
		height: 7rem;
		object-fit: contain;
		filter: drop-shadow(0 12px 18px rgba(82, 42, 16, 0.16));
	}
	.tater-brand h2 {
		margin: 0.12rem 0 0.35rem;
		font-size: clamp(1.35rem, 2.5vw, 2rem);
		font-weight: 760;
		letter-spacing: -0.035em;
		color: #342016;
	}
	.tater-brand p {
		max-width: 43rem;
		margin: 0;
		color: #846f65;
		font-size: 0.78rem;
		line-height: 1.65;
	}
	:global(.dark) .tater-brand h2 {
		color: #fff8ef;
	}
	:global(.dark) .tater-brand p {
		color: #b8a69c;
	}
	.tater-kicker {
		color: var(--tater-orange);
		font-size: 0.62rem;
		font-weight: 800;
		letter-spacing: 0.16em;
	}
	.tater-glow {
		position: absolute;
		border-radius: 999px;
		filter: blur(1px);
		opacity: 0.48;
	}
	.tater-glow-one {
		width: 14rem;
		height: 14rem;
		top: -8rem;
		right: 8%;
		background: radial-gradient(circle, rgba(242, 140, 40, 0.35), transparent 68%);
	}
	.tater-glow-two {
		width: 11rem;
		height: 11rem;
		bottom: -7rem;
		left: 32%;
		background: radial-gradient(circle, rgba(124, 92, 255, 0.2), transparent 70%);
	}
	.tater-status-pill {
		position: relative;
		z-index: 1;
		display: flex;
		flex: 0 0 auto;
		align-items: center;
		gap: 0.45rem;
		border: 1px solid rgba(242, 140, 40, 0.2);
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.72);
		padding: 0.5rem 0.75rem;
		color: #8b6b54;
		font-size: 0.68rem;
		font-weight: 700;
	}
	.tater-status-pill i {
		width: 0.48rem;
		height: 0.48rem;
		border-radius: 50%;
		background: #d7b18d;
		box-shadow: 0 0 0 0.22rem rgba(215, 177, 141, 0.16);
	}
	.tater-status-pill.online i {
		background: var(--tater-green);
		box-shadow:
			0 0 0 0.22rem rgba(85, 214, 139, 0.16),
			0 0 1rem rgba(85, 214, 139, 0.5);
	}
	:global(.dark) .tater-status-pill {
		background: rgba(22, 18, 20, 0.72);
		color: #cfb9aa;
	}

	.tater-unlinked-grid,
	.tater-linked-grid {
		display: grid;
		grid-template-columns: minmax(0, 1.05fr) minmax(20rem, 0.95fr);
		gap: 1rem;
	}
	.tater-card {
		border-radius: 1.25rem;
		padding: 1.25rem;
	}
	.tater-card h3 {
		margin: 0.15rem 0 0.35rem;
		color: #3a2419;
		font-size: 1rem;
		font-weight: 720;
	}
	.tater-card header p {
		margin: 0;
		color: #8d776a;
		font-size: 0.72rem;
		line-height: 1.55;
	}
	:global(.dark) .tater-card h3 {
		color: #fff7ee;
	}
	:global(.dark) .tater-card header p {
		color: #a9978e;
	}

	.tater-connect-card {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}
	.tater-connect-card label,
	.context-field {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		color: #6e584b;
		font-size: 0.69rem;
		font-weight: 680;
	}
	.tater-connect-card label small,
	.context-field small {
		color: #a08d82;
		font-size: 0.62rem;
		font-weight: 450;
		line-height: 1.45;
	}
	.tater-connect-card input,
	.context-field input {
		width: 100%;
		border: 1px solid rgba(113, 80, 58, 0.14);
		border-radius: 0.8rem;
		background: rgba(255, 255, 255, 0.7);
		padding: 0.72rem 0.8rem;
		color: #3d2b22;
		font-size: 0.75rem;
		outline: none;
		transition:
			border-color 0.16s,
			box-shadow 0.16s;
	}
	.tater-connect-card input:focus,
	.context-field input:focus {
		border-color: rgba(242, 140, 40, 0.65);
		box-shadow: 0 0 0 0.2rem rgba(242, 140, 40, 0.11);
	}
	:global(.dark) .tater-connect-card label,
	:global(.dark) .context-field {
		color: #c4b1a5;
	}
	:global(.dark) .tater-connect-card input,
	:global(.dark) .context-field input {
		border-color: rgba(255, 255, 255, 0.08);
		background: rgba(255, 255, 255, 0.035);
		color: #fff8f1;
	}

	.tater-primary,
	.tater-secondary,
	.tater-danger {
		border-radius: 0.8rem;
		padding: 0.68rem 0.9rem;
		font-size: 0.7rem;
		font-weight: 760;
		transition:
			transform 0.15s,
			opacity 0.15s,
			background 0.15s;
	}
	.tater-primary {
		border: 1px solid #dd7417;
		background: linear-gradient(135deg, var(--tater-orange-bright), var(--tater-orange));
		color: #2b1607;
		box-shadow: 0 0.65rem 1.4rem rgba(242, 140, 40, 0.2);
	}
	.tater-secondary {
		border: 1px solid rgba(242, 140, 40, 0.24);
		background: rgba(242, 140, 40, 0.08);
		color: #a95c19;
	}
	.tater-danger {
		border: 1px solid rgba(224, 85, 85, 0.2);
		background: rgba(224, 85, 85, 0.06);
		color: #c04e4e;
	}
	.tater-primary:not(:disabled):hover,
	.tater-secondary:not(:disabled):hover,
	.tater-danger:not(:disabled):hover {
		transform: translateY(-1px);
	}
	button:disabled {
		cursor: not-allowed;
		opacity: 0.48;
	}

	.route-list {
		display: grid;
		gap: 0.58rem;
		margin-top: 1rem;
	}
	.route-list > div {
		display: flex;
		align-items: center;
		gap: 0.7rem;
		border: 1px solid rgba(95, 65, 48, 0.08);
		border-radius: 0.85rem;
		background: rgba(255, 255, 255, 0.48);
		padding: 0.72rem;
	}
	.route-list i {
		width: 0.62rem;
		height: 0.62rem;
		flex: 0 0 auto;
		border-radius: 50%;
	}
	.route-list i.base {
		background: var(--tater-orange);
		box-shadow: 0 0 0.8rem rgba(242, 140, 40, 0.42);
	}
	.route-list i.terminal {
		background: var(--tater-green);
		box-shadow: 0 0 0.8rem rgba(85, 214, 139, 0.35);
	}
	.route-list i.hydra {
		background: var(--tater-purple);
		box-shadow: 0 0 0.8rem rgba(124, 92, 255, 0.4);
	}
	.route-list i.voice {
		background: #4cb8dd;
		box-shadow: 0 0 0.8rem rgba(76, 184, 221, 0.4);
	}
	.route-list span {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.route-list strong {
		color: #4b3326;
		font-size: 0.72rem;
	}
	.route-list small {
		color: #968176;
		font-size: 0.62rem;
	}
	:global(.dark) .route-list > div {
		border-color: rgba(255, 255, 255, 0.045);
		background: rgba(255, 255, 255, 0.025);
	}
	:global(.dark) .route-list strong {
		color: #f6e9df;
	}

	.card-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}
	.healthy {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		border-radius: 999px;
		background: rgba(85, 214, 139, 0.1);
		padding: 0.4rem 0.58rem;
		color: #27995a;
		font-size: 0.62rem;
		font-weight: 750;
	}
	.healthy i {
		width: 0.42rem;
		height: 0.42rem;
		border-radius: 50%;
		background: var(--tater-green);
		box-shadow: 0 0 0.75rem rgba(85, 214, 139, 0.65);
	}
	.connection-address {
		margin: 0.85rem 0;
		overflow: hidden;
		border-radius: 0.65rem;
		background: rgba(103, 73, 54, 0.055);
		padding: 0.58rem 0.7rem;
		color: #8b705f;
		font-family: ui-monospace, monospace;
		font-size: 0.65rem;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.capability-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.55rem;
	}
	.capability-grid > div {
		display: flex;
		align-items: center;
		gap: 0.55rem;
		border: 1px solid rgba(110, 76, 53, 0.08);
		border-radius: 0.78rem;
		padding: 0.68rem;
	}
	.capability-grid > div > i {
		width: 0.46rem;
		height: 0.46rem;
		flex: 0 0 auto;
		border-radius: 50%;
		background: #ccb7a7;
	}
	.capability-grid > div.ready > i {
		background: var(--tater-green);
		box-shadow: 0 0 0.65rem rgba(85, 214, 139, 0.45);
	}
	.capability-grid span {
		display: flex;
		min-width: 0;
		flex-direction: column;
		color: #9b8578;
		font-size: 0.59rem;
	}
	.capability-grid strong {
		overflow: hidden;
		color: #4b3428;
		font-size: 0.68rem;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	:global(.dark) .capability-grid > div {
		border-color: rgba(255, 255, 255, 0.05);
	}
	:global(.dark) .capability-grid strong {
		color: #f6e8df;
	}
	.verification-result {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		margin-top: 0.7rem;
		border-radius: 0.75rem;
		background: rgba(85, 214, 139, 0.08);
		padding: 0.65rem;
		color: #2f9d61;
	}
	.verification-result > span {
		font-weight: 900;
	}
	.verification-result div {
		display: flex;
		flex-direction: column;
		font-size: 0.65rem;
	}
	.verification-result small {
		color: #75a98b;
		font-size: 0.58rem;
	}
	.button-row {
		display: flex;
		justify-content: space-between;
		gap: 0.55rem;
		margin-top: 0.85rem;
	}

	.tater-workspace-card {
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
	}
	.model-pair {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.6rem;
	}
	.model-pair > div {
		display: flex;
		min-height: 6.2rem;
		flex-direction: column;
		border-radius: 0.9rem;
		padding: 0.8rem;
		background: linear-gradient(145deg, rgba(242, 140, 40, 0.09), rgba(124, 92, 255, 0.04));
	}
	.model-pair span {
		color: #b1733e;
		font-size: 0.56rem;
		font-weight: 800;
		letter-spacing: 0.12em;
	}
	.model-pair strong {
		margin-top: 0.25rem;
		color: #493126;
		font-family: ui-monospace, monospace;
		font-size: 0.78rem;
	}
	.model-pair small {
		margin-top: auto;
		color: #9b867b;
		font-size: 0.6rem;
		line-height: 1.4;
	}
	:global(.dark) .model-pair strong {
		color: #fff1e7;
	}
	.tater-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.6rem;
		padding: 3rem;
		color: #998075;
		font-size: 0.72rem;
	}
	.tater-loading span {
		width: 0.65rem;
		height: 0.65rem;
		border: 2px solid rgba(242, 140, 40, 0.25);
		border-top-color: var(--tater-orange);
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (max-width: 760px) {
		.tater-hero {
			align-items: flex-start;
			flex-direction: column;
		}
		.tater-brand {
			align-items: flex-start;
		}
		.tater-logo-shell {
			width: 5.2rem;
			height: 5.2rem;
			border-radius: 1.35rem;
		}
		.tater-logo-shell img {
			width: 5rem;
			height: 5rem;
		}
		.tater-unlinked-grid,
		.tater-linked-grid {
			grid-template-columns: 1fr;
		}
	}

	@media (max-width: 480px) {
		.tater-brand {
			flex-direction: column;
		}
		.capability-grid,
		.model-pair {
			grid-template-columns: 1fr;
		}
	}
</style>
