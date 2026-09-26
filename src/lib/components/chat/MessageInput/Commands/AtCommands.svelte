<script lang="ts">
	import Fuse from 'fuse.js';
	import { getContext, onDestroy } from 'svelte';

	import {
		chatId as activeChatId,
		models,
		selectedTerminalId,
		settings,
		terminalServers
	} from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { searchFiles } from '$lib/apis/terminal';
	import { decodeString } from '$lib/utils';
	import {
		resolveLocalizedModelDescription,
		resolveLocalizedModelName
	} from '$lib/utils/localizedContent';
	import { isTemporaryChatId } from '$lib/utils/chatId';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import DocumentPage from '$lib/components/icons/DocumentPage.svelte';
	import Folder from '$lib/components/icons/Folder.svelte';

	const i18n = getContext<any>('i18n');

	export let query = '';
	export let onSelect: (e: any) => void = () => {};

	let selectedIdx = 0;
	export let filteredItems: any[] = [];
	let searchDebounceTimer: ReturnType<typeof setTimeout>;

	let filesystemItems: any[] = [];
	let modelItems: any[] = [];
	let filteredModels: any[] = [];
	let contextItems: any[] = [];

	$: modelItems = (($models ?? []) as any[])
		.filter((model) => !model?.info?.meta?.hidden)
		.map((model) => ({
			...model,
			modelName: resolveLocalizedModelName(model, $i18n.language),
			tags: model?.info?.meta?.tags?.map((tag: any) => tag.name).join(' '),
			desc: resolveLocalizedModelDescription(model, $i18n.language)
		}));

	$: fuse = new Fuse(modelItems, {
		keys: ['value', 'tags', 'modelName'],
		threshold: 0.5
	});

	$: filteredModels = query ? fuse.search(query).map((e) => e.item) : modelItems;
	$: contextItems = filesystemItems;

	$: filteredItems = [
		...contextItems.map((data) => ({ type: data.type, data })),
		...filteredModels.map((data) => ({ type: 'model', data }))
	];

	$: if (query) {
		selectedIdx = 0;
	}

	$: selectedIdx = Math.min(selectedIdx, Math.max(filteredItems.length - 1, 0));

	$: if (query !== undefined) {
		clearTimeout(searchDebounceTimer);
		searchDebounceTimer = setTimeout(() => {
			getItems();
		}, 200);
	}

	onDestroy(() => {
		clearTimeout(searchDebounceTimer);
	});

	const getItems = () => {
		const terminal = getSelectedTerminal();
		getFilesystemItems(terminal);
	};

	const getFilesystemItems = async (terminal = getSelectedTerminal()) => {
		if (!terminal) {
			filesystemItems = [];
			return;
		}

		const res = await searchFiles(
			terminal.url,
			terminal.key,
			query,
			'.',
			20,
			'any',
			$activeChatId || undefined,
			localStorage.getItem('fileNav:showHidden') === 'true'
		).catch(() => null);

		filesystemItems = (res?.results ?? []).map((item: any) => ({
			...item,
			type: 'filesystem',
			filesystem_type: item.type,
			id: item.path,
			url: item.path,
			name: item.name,
			description: item.path,
			status: 'processed'
		}));
	};

	const chatContext = (terminal: any) => terminal?.contexts?.chat ?? {};

	const getSelectedTerminal = (): { url: string; key: string } | null => {
		if (!$selectedTerminalId) return null;

		const systemTerminal = ($terminalServers ?? []).find(
			(t) => t.id && t.id === $selectedTerminalId
		);
		const systemChatContext = chatContext(systemTerminal);
		if (systemTerminal) {
			if (
				systemChatContext === false ||
				(isTemporaryChatId($activeChatId) && systemChatContext?.context_id === 'chat_id')
			) {
				return null;
			}

			return { url: systemTerminal.url, key: localStorage.token };
		}

		const directTerminal = ($settings?.terminalServers ?? []).find(
			(t: any) => t.url === $selectedTerminalId && t.enabled
		);
		return directTerminal?.url ? { url: directTerminal.url, key: directTerminal.key ?? '' } : null;
	};

	const selectContextItem = (item: any) => {
		if (item.type === 'filesystem') {
			onSelect({ type: 'filesystem', data: item });
		}
	};

	export const selectUp = () => {
		selectedIdx = Math.max(0, selectedIdx - 1);
	};

	export const selectDown = () => {
		selectedIdx = Math.min(selectedIdx + 1, filteredItems.length - 1);
	};

	export const select = async () => {
		const item = filteredItems[selectedIdx];
		if (!item) return;

		if (item.type === 'model') {
			onSelect({ type: 'model', data: item.data });
		} else {
			selectContextItem(item.data);
		}
	};
</script>

{#if contextItems.length > 0}
	{#each contextItems as item, idx}
		{@const itemIdx = idx}
		{#if idx === 0 || item?.type !== contextItems[idx - 1]?.type}
			<div class="px-2 py-1 text-[0.6875rem] text-gray-500 dark:text-gray-400">
				{#if item?.type === 'filesystem'}
					{$i18n.t('Filesystem')}
				{/if}
			</div>
		{/if}

		<button
			class="flex h-[1.6875rem] w-full max-w-full items-center justify-between overflow-hidden rounded-xl px-2 text-left text-[0.8125rem] hover:bg-gray-50/40 dark:hover:bg-gray-800/40 {itemIdx ===
			selectedIdx
				? 'bg-gray-50/40 dark:bg-gray-800/40 dark:text-gray-100 selected-command-option-button'
				: ''}"
			type="button"
			on:click={() => {
				selectContextItem(item);
			}}
			on:mousemove={() => {
				selectedIdx = itemIdx;
			}}
			data-selected={itemIdx === selectedIdx}
		>
			<div
				class="flex w-full min-w-0 items-center gap-1.5 overflow-hidden text-black dark:text-gray-100"
			>
				<Tooltip
					className="shrink-0 flex"
					content={item?.path ?? ''}
					placement="top"
				>
					{#if item?.filesystem_type === 'directory'}
						<Folder className="size-3.5" />
					{:else}
						<DocumentPage className="size-3.5" />
					{/if}
				</Tooltip>

				<Tooltip
					className="min-w-0 flex-1"
					content={`${decodeString(item?.name)}`}
					placement="top-start"
				>
					<div class="line-clamp-1 min-w-0 overflow-hidden break-all">
						{decodeString(item?.name)}
					</div>
				</Tooltip>
			</div>
		</button>
	{/each}
{/if}

{#if filteredModels.length > 0}
	<div class="px-2 py-1 text-[0.6875rem] text-gray-500 dark:text-gray-400">
		{$i18n.t('Models')}
	</div>

	{#each filteredModels as model, modelIdx}
		{@const itemIdx = contextItems.length + modelIdx}
		<Tooltip content={model.id} placement="top-start">
			<button
				class="flex h-[1.6875rem] w-full items-center rounded-xl px-2 text-left text-[0.8125rem] hover:bg-gray-50/40 dark:hover:bg-gray-800/40 {itemIdx ===
				selectedIdx
					? 'bg-gray-50/40 dark:bg-gray-800/40 selected-command-option-button'
					: ''}"
				type="button"
				on:click={() => {
					onSelect({ type: 'model', data: model });
				}}
				on:mousemove={() => {
					selectedIdx = itemIdx;
				}}
				on:focus={() => {}}
				data-selected={itemIdx === selectedIdx}
			>
				<div class="flex min-w-0 items-center text-black dark:text-gray-100">
					<img
						src={`${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model.id}&lang=${$i18n.language}`}
						alt={resolveLocalizedModelName(model, $i18n.language) ?? model.id}
						class="mr-2 size-4.5 rounded-full object-cover"
						on:error={(e) => {
							// LICENSE covers this Open WebUI fallback logo.
							// Do not alter, remove, obscure, or replace it except as LICENSE permits:
							// https://docs.openwebui.com/license.
							(e.currentTarget as HTMLImageElement).src = '/favicon.png';
						}}
					/>
					<div class="min-w-0 truncate">
						{resolveLocalizedModelName(model, $i18n.language)}
					</div>
				</div>
			</button>
		</Tooltip>
	{/each}
{/if}
