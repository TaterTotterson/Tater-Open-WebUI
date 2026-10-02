<script lang="ts">
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');
	import { fade } from 'svelte/transition';
	import { settings } from '$lib/stores';
	import {
		normalizeActivityAnimation,
		type TaterActivityAnimation
	} from '$lib/utils/taterAppearance';

	import StatusItem from './StatusHistory/StatusItem.svelte';
	import equal from 'fast-deep-equal';
	export let statusHistory: any[] = [];
	export let expand = false;

	let showHistory = true;

	$: if (expand) {
		showHistory = true;
	} else {
		showHistory = false;
	}

	let history: any[] = [];
	let status: any = null;
	let statusKey = '';
	let activityAnimation: TaterActivityAnimation = 'fade';

	$: if (history && history.length > 0) {
		status = history.at(-1);
	}

	$: if (!equal(statusHistory, history)) {
		history = statusHistory;
	}

	$: activityAnimation = normalizeActivityAnimation($settings?.taterActivityAnimation);
	$: statusKey = `${activityAnimation}:${status?.id ?? ''}:${status?.description ?? ''}:${status?.detail ?? ''}:${status?.done ?? ''}`;
</script>

{#if history && history.length > 0}
	{#if status?.hidden !== true}
		<div class="text-[0.9375rem] flex flex-col w-full">
			<button
				class="w-full"
				aria-label={$i18n.t('Toggle status history')}
				aria-expanded={showHistory}
				on:click={() => {
					showHistory = !showHistory;
				}}
			>
				{#key statusKey}
					{#if activityAnimation === 'fade'}
						<div
							class="flex items-start gap-2"
							in:fade={{ duration: 220 }}
							out:fade={{ duration: 100 }}
						>
							<StatusItem {status} />
						</div>
					{:else}
						<div class="flex items-start gap-2">
							<StatusItem {status} animate={true} animation={activityAnimation} />
						</div>
					{/if}
				{/key}
			</button>

			{#if showHistory}
				<div class="flex flex-row">
					{#if history.length > 1}
						<div class="w-full">
							{#each history as status, idx}
								<div class="flex items-stretch gap-2 mb-1">
									<div class=" ">
										<div class="pt-3 px-1 mb-1.5">
											<span class="relative flex size-1.5 rounded-full justify-center items-center">
												<span
													class="relative inline-flex size-1.5 rounded-full bg-gray-500 dark:bg-gray-400"
												></span>
											</span>
										</div>
										{#if idx !== history.length - 1}
											<div
												class="w-[0.03125rem] ml-[0.40625rem] h-[calc(100%-14px)] bg-gray-300 dark:bg-gray-700"
											></div>
										{/if}
									</div>

									<StatusItem {status} done={true} />
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/if}
{/if}
