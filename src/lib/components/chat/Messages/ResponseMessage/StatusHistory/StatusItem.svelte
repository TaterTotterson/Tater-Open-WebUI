<script>
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');
	import Search from '$lib/components/icons/Search.svelte';
	import { t } from 'i18next';

	export let status = null;
	export let done = false;
</script>

{#if !status?.hidden}
	<div class="status-description flex items-center gap-2 py-0.5 w-full text-left">
		{#if status?.action === 'queries_generated' && status?.queries}
			<div class="flex flex-col justify-center -space-y-0.5">
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-[0.9375rem] line-clamp-1 text-wrap"
				>
					{$i18n.t(`Querying`)}
				</div>

				<div class=" flex gap-1 flex-wrap mt-2">
					{#each status.queries as query, idx (query)}
						<div
							class="bg-gray-50 dark:bg-gray-850 flex rounded-lg py-1 px-2 items-center gap-1 text-xs"
						>
							<div>
								<Search className="size-3" />
							</div>

							<span class="line-clamp-1">
								{query}
							</span>
						</div>
					{/each}
				</div>
			</div>
		{:else if status?.action === 'sources_retrieved' && status?.count !== undefined}
			<div class="flex flex-col justify-center -space-y-0.5">
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-[0.9375rem] line-clamp-1 text-wrap"
				>
					{#if status.count === 0}
						{$i18n.t('No sources found')}
					{:else if status.count === 1}
						{$i18n.t('Retrieved 1 source')}
					{:else}
						<!-- {$i18n.t('Source')} -->
						<!-- {$i18n.t('No source available')} -->
						<!-- {$i18n.t('No distance available')} -->
						<!-- {$i18n.t('Retrieved {{count}} sources')} -->
						{$i18n.t('Retrieved {{count}} sources', {
							count: status.count
						})}
					{/if}
				</div>
			</div>
		{:else}
			<div class="flex min-w-0 flex-col justify-center gap-0.5">
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-[0.9375rem] line-clamp-1 text-wrap"
				>
					<!-- $i18n.t(`Searching "{{searchQuery}}"`) -->
					{#if status?.description?.includes('{{searchQuery}}')}
						{$i18n.t(status?.description, {
							searchQuery: status?.query
						})}
					{:else if status?.description === 'No search query generated'}
						{$i18n.t('No search query generated')}
					{:else if status?.description === 'Generating search query'}
						{$i18n.t('Generating search query')}
					{:else if status?.description === 'Searching the web'}
						{$i18n.t('Searching the web')}
					{:else}
						{status?.description}
					{/if}
				</div>
				{#if status?.detail}
					<div
						class="max-w-full truncate font-mono text-[0.75rem] text-gray-400 dark:text-gray-600"
						title={status.detail}
					>
						{status.detail}
					</div>
				{/if}
			</div>
		{/if}
	</div>
{/if}
