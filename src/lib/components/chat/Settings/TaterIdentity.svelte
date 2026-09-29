<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getTaterIdentity,
		registerTaterIdentity,
		type TaterIdentity
	} from '$lib/apis/tater';

	let identity: TaterIdentity | null = null;
	let loading = true;
	let connecting = false;

	const load = async () => {
		loading = true;
		try {
			identity = await getTaterIdentity(localStorage.token);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			loading = false;
		}
	};

	const connectAccount = async () => {
		if (connecting) return;
		connecting = true;
		try {
			identity = await registerTaterIdentity(localStorage.token);
			toast.success(
				identity.linked
					? `This account is linked to ${identity.person?.name || 'a Tater Person'}`
					: 'Account sent to Tater. Link it in Settings > People.'
			);
		} catch (error) {
			toast.error(error instanceof Error ? error.message : String(error));
		} finally {
			connecting = false;
		}
	};

	onMount(load);
</script>

<div class="identity-page">
	<section class="identity-hero">
		<div class="brand-mark">
			<img src="/static/tater-open-webui-logo.png" alt="Tater Open WebUI" />
		</div>
		<div class="hero-copy">
			<span class="eyebrow">YOUR TATER IDENTITY</span>
			<h2>Connect this account to a Person</h2>
			<p>
				Your WebUI login stays separate from the shared SpudLink connection. Tater uses this
				identity only for Hydra tools, personal context, and permissions.
			</p>
		</div>
	</section>

	{#if loading}
		<div class="loading"><span></span>Checking your Tater identity…</div>
	{:else if !identity?.connected}
		<section class="state-card disconnected">
			<div class="state-icon">×</div>
			<div>
				<span class="eyebrow">NOT CONNECTED</span>
				<h3>Tater Open WebUI needs a SpudLink connection</h3>
				<p>An administrator can connect this installation in Admin Settings → Tater Open WebUI.</p>
			</div>
		</section>
	{:else if identity.linked}
		<section class="state-card linked">
			<div class="state-icon">✓</div>
			<div class="state-main">
				<span class="eyebrow">LINKED PERSON</span>
				<h3>{identity.person?.name || 'Tater Person'}</h3>
				<p>
					Hydra recognizes this login as {identity.person?.name || 'this Person'}.
					{identity.person?.is_admin
						? ' Admin-only Tater tools are available.'
						: ' Admin-only Tater tools remain restricted.'}
				</p>
				<div class="chips">
					<span>{identity.identity.label || 'WebUI account'}</span>
					<span>{identity.hub_name || 'Tater'}</span>
					{#if identity.person?.is_admin}<span class="admin-chip">Admin</span>{/if}
				</div>
			</div>
			<button type="button" class="secondary" on:click={load}>Refresh</button>
		</section>
	{:else if identity.registered}
		<section class="state-card pending">
			<div class="state-icon">•••</div>
			<div class="state-main">
				<span class="eyebrow">WAITING FOR LINK</span>
				<h3>Your account is visible in Tater</h3>
				<p>
					In Tater, open Settings → People → Identities and link
					<strong>{identity.identity.label || 'this account'}</strong> to the right Person.
				</p>
			</div>
			<button type="button" class="secondary" on:click={load}>Check again</button>
		</section>
	{:else}
		<section class="state-card ready">
			<div class="state-icon">↗</div>
			<div class="state-main">
				<span class="eyebrow">READY TO CONNECT</span>
				<h3>Introduce this WebUI account to Tater</h3>
				<p>
					This creates a discovered identity in Tater. A Tater administrator can then choose which
					Person it belongs to.
				</p>
			</div>
			<button type="button" class="primary" disabled={connecting} on:click={connectAccount}>
				{connecting ? 'Connecting…' : 'Connect this account'}
			</button>
		</section>
	{/if}

	<section class="note-card">
		<div><strong>Normal chat and terminal</strong><span>Always stay local to this WebUI account.</span></div>
		<div><strong>Hydra calls</strong><span>Carry this stable identity to Tater for tools and permissions.</span></div>
		<div><strong>Multiple logins</strong><span>Each WebUI login can link to a different Tater Person.</span></div>
	</section>
</div>

<style>
	.identity-page { height: 100%; overflow-y: auto; padding: .25rem .25rem 2rem; color: rgb(31 41 55); }
	:global(.dark) .identity-page { color: rgb(243 244 246); }
	.identity-hero { position: relative; display: flex; gap: 1.25rem; align-items: center; padding: 1.4rem; border: 1px solid rgba(249,115,22,.2); border-radius: 1.5rem; background: linear-gradient(135deg, rgba(255,247,237,.95), rgba(255,255,255,.75)); overflow: hidden; }
	:global(.dark) .identity-hero { background: linear-gradient(135deg, rgba(67,32,11,.65), rgba(17,24,39,.9)); border-color: rgba(251,146,60,.22); }
	.brand-mark { width: 5.5rem; height: 5.5rem; flex: none; border-radius: 1.35rem; padding: .55rem; background: rgba(255,255,255,.82); box-shadow: 0 16px 42px rgba(124,45,18,.14); }
	:global(.dark) .brand-mark { background: rgba(255,255,255,.08); }
	.brand-mark img { width: 100%; height: 100%; object-fit: contain; }
	.hero-copy h2, .state-card h3 { margin: .2rem 0 .35rem; font-weight: 700; letter-spacing: -.025em; }
	.hero-copy h2 { font-size: 1.45rem; }
	.hero-copy p, .state-card p { margin: 0; color: rgb(107 114 128); font-size: .875rem; line-height: 1.55; }
	:global(.dark) .hero-copy p, :global(.dark) .state-card p { color: rgb(156 163 175); }
	.eyebrow { color: rgb(234 88 12); font-size: .65rem; font-weight: 800; letter-spacing: .13em; }
	.loading, .state-card, .note-card { margin-top: 1rem; border: 1px solid rgb(243 244 246); border-radius: 1.25rem; background: rgba(255,255,255,.8); }
	:global(.dark) .loading, :global(.dark) .state-card, :global(.dark) .note-card { border-color: rgba(255,255,255,.06); background: rgba(255,255,255,.025); }
	.loading { display: flex; align-items: center; gap: .7rem; padding: 1.25rem; font-size: .85rem; color: rgb(107 114 128); }
	.loading span { width: .7rem; height: .7rem; border-radius: 999px; background: rgb(249 115 22); box-shadow: 0 0 0 .35rem rgba(249,115,22,.12); animation: pulse 1.2s infinite; }
	.state-card { display: flex; align-items: center; gap: 1rem; padding: 1.25rem; }
	.state-icon { display: grid; place-items: center; width: 2.75rem; height: 2.75rem; flex: none; border-radius: .9rem; color: white; background: rgb(249 115 22); font-weight: 800; }
	.linked .state-icon { background: rgb(22 163 74); }
	.pending .state-icon { background: rgb(234 179 8); }
	.disconnected .state-icon { background: rgb(107 114 128); }
	.state-main { min-width: 0; flex: 1; }
	.chips { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .8rem; }
	.chips span { padding: .28rem .55rem; border-radius: 999px; background: rgb(243 244 246); color: rgb(75 85 99); font-size: .7rem; font-weight: 600; }
	:global(.dark) .chips span { background: rgba(255,255,255,.07); color: rgb(209 213 219); }
	.chips .admin-chip { background: rgba(249,115,22,.13); color: rgb(234 88 12); }
	button { flex: none; border-radius: .8rem; padding: .65rem .9rem; font-size: .78rem; font-weight: 700; transition: transform .12s ease, opacity .12s ease; }
	button:hover:not(:disabled) { transform: translateY(-1px); }
	button:disabled { opacity: .55; }
	.primary { color: white; background: linear-gradient(135deg, rgb(249 115 22), rgb(234 88 12)); box-shadow: 0 10px 24px rgba(234,88,12,.2); }
	.secondary { color: rgb(194 65 12); background: rgba(249,115,22,.1); }
	.note-card { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 1px; overflow: hidden; background: rgb(243 244 246); }
	:global(.dark) .note-card { background: rgba(255,255,255,.06); }
	.note-card div { display: flex; flex-direction: column; gap: .25rem; padding: 1rem; background: white; }
	:global(.dark) .note-card div { background: rgb(17 24 39); }
	.note-card strong { font-size: .77rem; }
	.note-card span { color: rgb(107 114 128); font-size: .72rem; line-height: 1.45; }
	@keyframes pulse { 50% { opacity: .45; } }
	@media (max-width: 700px) { .identity-hero { align-items: flex-start; } .brand-mark { width: 4rem; height: 4rem; } .state-card { align-items: flex-start; flex-wrap: wrap; } .state-main { flex-basis: calc(100% - 4rem); } .state-card button { margin-left: 3.75rem; } .note-card { grid-template-columns: 1fr; } }
</style>
