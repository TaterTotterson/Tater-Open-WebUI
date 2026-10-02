<script lang="ts">
	import { fade, fly } from 'svelte/transition';

	import CheckCircle from '$lib/components/icons/CheckCircle.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Terminal from '$lib/components/icons/Terminal.svelte';

	export let history: any[] = [];

	let showCommands = true;

	$: summaries = history.filter((item) => item?.action === 'tater_agent_progress');
	$: summary = summaries.at(-1) ?? null;
	$: tools = history.filter((item) => item?.action === 'tool_execution');
	$: runningTools = tools.filter((item) => item?.done !== true).length;
	$: completedTools = tools.length - runningTools;
	$: isDone = summary?.done === true;
	$: isError = summary?.error === true;
	$: stateLabel = isError ? 'Needs attention' : isDone ? 'Work complete' : 'Working';
	$: summaryKey = `${summary?.description ?? ''}:${isDone}:${isError}`;

	const toolLabel = (tool: any) => {
		if (tool?.tool === 'terminal') return 'Terminal';
		if (tool?.tool === 'tater_hydra') return 'Tater Hydra';
		return tool?.tool || 'Tool';
	};
</script>

<div
	class="my-1.5 overflow-hidden rounded-2xl border border-orange-200/70 bg-gradient-to-br from-orange-50/90 via-white/80 to-amber-50/70 shadow-sm shadow-orange-100/50 dark:border-orange-900/50 dark:from-orange-950/25 dark:via-gray-900/70 dark:to-amber-950/20 dark:shadow-none"
>
	<div class="flex items-start gap-3 px-3.5 py-3">
		<div
			class="relative mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-xl border border-orange-200 bg-orange-100 text-orange-700 dark:border-orange-800/70 dark:bg-orange-900/50 dark:text-orange-300"
		>
			{#if isDone && !isError}
				<CheckCircle className="size-4" strokeWidth="1.8" />
			{:else}
				<Sparkles className="size-4" strokeWidth="1.8" />
				{#if !isDone}
					<span class="agent-orb absolute -right-0.5 -top-0.5 size-2 rounded-full bg-orange-500"
					></span>
				{/if}
			{/if}
		</div>

		<div class="min-w-0 flex-1">
			<div
				class="mb-0.5 text-[0.68rem] font-semibold uppercase tracking-[0.14em] {isError
					? 'text-red-600 dark:text-red-400'
					: 'text-orange-700 dark:text-orange-300'}"
			>
				{stateLabel}
			</div>
			{#key summaryKey}
				<p
					class="m-0 text-[0.9rem] leading-5 text-gray-700 dark:text-gray-200"
					in:fade={{ duration: 220 }}
					out:fade={{ duration: 100 }}
				>
					{summary?.description ?? 'Working through the request.'}
				</p>
			{/key}
		</div>
	</div>

	{#if tools.length > 0}
		<div class="border-t border-orange-200/60 dark:border-orange-900/40">
			<button
				type="button"
				class="flex w-full items-center gap-2 px-3.5 py-2 text-left text-xs text-gray-500 transition-colors hover:bg-orange-100/50 dark:text-gray-400 dark:hover:bg-orange-950/30"
				aria-expanded={showCommands}
				on:click={() => (showCommands = !showCommands)}
			>
				<Terminal className="size-3.5 text-orange-600 dark:text-orange-400" strokeWidth="1.8" />
				<span class="font-medium text-gray-700 dark:text-gray-300">
					{tools.length}
					{tools.length === 1 ? 'command' : 'commands'}
				</span>
				<span class="text-gray-400 dark:text-gray-500">
					{runningTools > 0 ? `${runningTools} running` : `${completedTools} finished`}
				</span>
				<span class="ml-auto transition-transform duration-200 {showCommands ? 'rotate-180' : ''}">
					<ChevronDown className="size-3.5" />
				</span>
			</button>

			{#if showCommands}
				<div
					class="space-y-1.5 border-t border-orange-100/80 px-3.5 py-2.5 dark:border-orange-950/50"
					transition:fade={{ duration: 150 }}
				>
					{#each tools as tool (tool.id)}
						<div
							class="flex min-w-0 items-start gap-2 rounded-lg bg-white/60 px-2.5 py-2 dark:bg-black/15"
							in:fly={{ y: 4, duration: 180 }}
						>
							{#key `${tool.id}:${tool.done}:${tool.error}`}
								<span
									class="mt-1 size-1.5 shrink-0 rounded-full {tool?.error
										? 'bg-red-500'
										: tool?.done
											? 'bg-emerald-500'
											: 'agent-command-pulse bg-orange-500'}"
									transition:fade={{ duration: 150 }}
								></span>
							{/key}
							<div class="min-w-0 flex-1">
								<div class="text-[0.72rem] font-medium text-gray-600 dark:text-gray-300">
									{toolLabel(tool)} · {tool?.error ? 'Failed' : tool?.done ? 'Finished' : 'Running'}
								</div>
								{#if tool?.detail}
									<div
										class="mt-0.5 truncate font-mono text-[0.7rem] text-gray-400 dark:text-gray-500"
										title={tool.detail}
									>
										{tool.detail}
									</div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.agent-orb::after {
		position: absolute;
		inset: 0;
		content: '';
		border-radius: 9999px;
		background: currentColor;
		animation: agent-orb 1.6s ease-out infinite;
	}

	.agent-command-pulse {
		animation: agent-command-pulse 1.2s ease-in-out infinite;
	}

	@keyframes agent-orb {
		0% {
			opacity: 0.55;
			transform: scale(1);
		}
		75%,
		100% {
			opacity: 0;
			transform: scale(2.4);
		}
	}

	@keyframes agent-command-pulse {
		0%,
		100% {
			opacity: 0.45;
		}
		50% {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.agent-orb::after,
		.agent-command-pulse {
			animation: none;
		}
	}
</style>
