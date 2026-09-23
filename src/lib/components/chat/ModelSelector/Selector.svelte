<script lang="ts">
	import Fuse from 'fuse.js';
	import { autoUpdate, computePosition, flip, offset, shift, size } from '@floating-ui/dom';

	import { flyAndScale } from '$lib/utils/transitions';

	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';

	import { user, mobile, models, settings, showSettings } from '$lib/stores';
	import {
		resolveLocalizedModelDescription,
		resolveLocalizedModelName
	} from '$lib/utils/localizedContent';
	import { getModels } from '$lib/apis';

	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ChatBubbleOval from '$lib/components/icons/ChatBubbleOval.svelte';
	import Keyframes from '$lib/components/icons/Keyframes.svelte';
	import TagSelector from '$lib/components/workspace/common/TagSelector.svelte';

	import ModelItem from './ModelItem.svelte';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let id = '';
	export let value: string | null = '';
	export let values: string[] | null = null;
	export let compareEnabled = false;
	export let multipleEnabled = false;
	export let disabled = false;
	export let placeholder = $i18n.t('Select a model');
	export let searchEnabled = true;
	export let searchPlaceholder = $i18n.t('Search a model');
	export let selectionOnly = false;
	export let includeHidden = false;

	export let items: {
		label: string;
		value: string;
		model: Model;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		[key: string]: any;
	}[] = [];

	export let className = 'w-[20rem]';
	export let triggerClassName = 'text-lg';
	export let placement: 'top' | 'bottom' | 'auto' = 'bottom';
	export let align: 'start' | 'end' = 'start';
	export let showSetDefault = false;
	export let onSetDefault: () => Promise<void> | void = () => {};

	export let pinModelHandler: (modelId: string) => void = () => {};

	let show = false;
	let triggerElement: HTMLElement | null = null;
	let contentElement: HTMLElement | null = null;
	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		const panel = node.firstElementChild as HTMLElement;
		const cleanup = autoUpdate(triggerElement!, node, () => {
			// Let flip measure the full list after content or viewport changes.
			panel.style.maxHeight = '';
			computePosition(triggerElement!, node, {
				strategy: 'fixed',
				placement: `${placement === 'auto' ? 'bottom' : placement}-${align}`,
				middleware: [
					offset(2),
					placement === 'auto' && flip({ padding: 8, crossAxis: false }),
					shift({ padding: 8 }),
					size({
						padding: 8,
						apply({ availableHeight, availableWidth }) {
							panel.style.maxHeight = `${Math.max(0, availableHeight)}px`;
							panel.style.maxWidth = `${Math.max(0, availableWidth)}px`;
						}
					})
				]
			}).then(({ x, y }) => {
				node.style.left = `${x}px`;
				node.style.top = `${y}px`;
			});
		});

		return {
			destroy() {
				cleanup();
				node.remove();
			}
		};
	};

	const focusSearchInput = () => {
		if (!$mobile) {
			document.getElementById('model-search-input')?.focus();
		}
	};
	const focusChatInput = () => {
		if (!$mobile) {
			document.getElementById('chat-input')?.focus();
		}
	};

	const toggleOpen = async () => {
		show = !show;
		if (show) {
			searchValue = '';
			listScrollTop = 0;
			resetView();
			await tick();
			for (const delay of [0, 50, 150]) {
				window.setTimeout(focusSearchInput, delay);
			}
		} else {
			document.getElementById(`model-selector-${id}-button`)?.blur();
		}
	};

	export const open = async () => {
		if (!show) {
			await toggleOpen();
		}
	};

	const handlePointerDown = (e: PointerEvent) => {
		if (!show) return;
		const target = e.target as Node;
		if (
			(triggerElement && triggerElement.contains(target)) ||
			(contentElement && contentElement.contains(target)) ||
			((target as HTMLElement).closest?.('.model-selector-child-menu') ?? false)
		) {
			return;
		}
		show = false;
		document.getElementById(`model-selector-${id}-button`)?.blur();
	};

	const handleKeydown = (e: KeyboardEvent) => {
		if (show && e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			show = false;
			document.getElementById(`model-selector-${id}-button`)?.blur();
		}
	};

	let tags = [];

	let selectedModel = '';
	$: selectedValues = values ?? (value ? [value] : []);
	$: primaryValue = selectedValues[0] ?? value ?? '';
	$: selectedModel = items.find((item) => item.value === primaryValue) ?? '';
	$: selectedCount = selectedValues.filter(Boolean).length;
	$: triggerLabel = selectedModel
		? compareEnabled && selectedCount > 1
			? `${selectedModel.label} +${selectedCount - 1}`
			: selectedModel.label
		: placeholder;

	let searchValue = '';

	let selectedTag = '';
	let selectedConnectionType = '';
	let selectedFilter = '';
	let modelFilterItems = [];

	let selectedModelIdx = 0;

	const fuse = new Fuse(
		items.map((item) => {
			const _item = {
				...item,
				modelName: resolveLocalizedModelName(item.model, $i18n.language),
				tags: (item.model?.tags ?? []).map((tag) => tag.name).join(' '),
				desc: resolveLocalizedModelDescription(item.model, $i18n.language)
			};
			return _item;
		}),
		{
			keys: ['value', 'tags', 'modelName'],
			threshold: 0.4
		}
	);

	const updateFuse = () => {
		if (fuse) {
			fuse.setCollection(
				items.map((item) => {
					const _item = {
						...item,
						modelName: resolveLocalizedModelName(item.model, $i18n.language),
						tags: (item.model?.tags ?? []).map((tag) => tag.name).join(' '),
						desc: resolveLocalizedModelDescription(item.model, $i18n.language)
					};
					return _item;
				})
			);
		}
	};

	$: if (items) {
		updateFuse();
	}

	$: filteredItems = (
		searchValue
			? fuse
					.search(searchValue)
					.map((e) => {
						return e.item;
					})
					.filter((item) => {
						if (selectedTag === '') {
							return true;
						}

						return (item.model?.tags ?? [])
							.map((tag) => tag.name.toLowerCase())
							.includes(selectedTag.toLowerCase());
					})
					.filter((item) => {
						if (selectedConnectionType === '') {
							return true;
						} else if (selectedConnectionType === 'local') {
							return item.model?.connection_type === 'local';
						} else if (selectedConnectionType === 'external') {
							return item.model?.connection_type === 'external';
						}
					})
			: items
					.filter((item) => {
						if (selectedTag === '') {
							return true;
						}
						return (item.model?.tags ?? [])
							.map((tag) => tag.name.toLowerCase())
							.includes(selectedTag.toLowerCase());
					})
					.filter((item) => {
						if (selectedConnectionType === '') {
							return true;
						} else if (selectedConnectionType === 'local') {
							return item.model?.connection_type === 'local';
						} else if (selectedConnectionType === 'external') {
							return item.model?.connection_type === 'external';
						}
					})
	).filter((item) => includeHidden || !(item.model?.info?.meta?.hidden ?? false));

	$: if (
		selectedTag !== undefined ||
		selectedConnectionType !== undefined ||
		searchValue !== undefined
	) {
		resetView();
	}

	$: modelFilterItems = [
		...(items.find((item) => item.model?.connection_type === 'local')
			? [{ value: 'connection:local', label: $i18n.t('Local') }]
			: []),
		...(items.find((item) => item.model?.connection_type === 'external')
			? [{ value: 'connection:external', label: $i18n.t('External') }]
			: []),
		...tags.map((tag) => ({ value: `tag:${tag}`, label: tag }))
	];

	$: selectedFilter = selectedConnectionType
		? `connection:${selectedConnectionType}`
		: selectedTag
			? `tag:${selectedTag}`
			: '';

	const setModelFilter = (filterValue: string) => {
		if (!filterValue) {
			selectedConnectionType = '';
			selectedTag = '';
		} else if (filterValue.startsWith('connection:')) {
			selectedConnectionType = filterValue.replace('connection:', '');
			selectedTag = '';
		} else if (filterValue.startsWith('tag:')) {
			selectedConnectionType = '';
			selectedTag = filterValue.replace('tag:', '');
		}
	};

	const resetView = async () => {
		await tick();

		const selectedInFiltered = filteredItems.findIndex((item) => item.value === primaryValue);

		if (selectedInFiltered >= 0) {
			// The selected model is visible in the current filter
			selectedModelIdx = selectedInFiltered;
		} else {
			// The selected model is not visible, default to first item in filtered list
			selectedModelIdx = 0;
		}

		// Set the virtual scroll position so the selected item is rendered and centered
		const targetScrollTop = Math.max(0, selectedModelIdx * ITEM_HEIGHT - 128 + ITEM_HEIGHT / 2);
		listScrollTop = targetScrollTop;

		await tick();

		if (listContainer) {
			listContainer.scrollTop = targetScrollTop;
		}

		await tick();
		const item = document.querySelector(`[data-arrow-selected="true"]`);
		item?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
	};

	const setCompareEnabled = (enabled: boolean) => {
		compareEnabled = enabled;

		if (!enabled && values) {
			values = [primaryValue || selectedValues[0] || ''];
			value = values[0];
		}
	};

	const selectItem = (item, index: number) => {
		selectedModelIdx = index;

		if (values) {
			if (compareEnabled) {
				const nextValues = selectedValues.includes(item.value)
					? selectedValues.length > 1
						? selectedValues.filter((selectedValue) => selectedValue !== item.value)
						: selectedValues
					: [...selectedValues.filter(Boolean), item.value];

				values = nextValues.length ? nextValues : [item.value];
				value = values[0];
				return;
			}

			values = [item.value];
			value = item.value;
			show = false;
			window.setTimeout(focusChatInput, 0);
			return;
		}

		value = item.value;
		show = false;
		window.setTimeout(focusChatInput, 0);
	};

	const setDefaultHandler = async () => {
		await onSetDefault();
	};

	onMount(() => {
		if (items) {
			tags = items
				.filter((item) => includeHidden || !(item.model?.info?.meta?.hidden ?? false))
				.flatMap((item) => item.model?.tags ?? [])
				.map((tag) => tag.name.toLowerCase());
			// Remove duplicates and sort
			tags = Array.from(new Set(tags)).sort((a, b) => a.localeCompare(b));
		}
	});

	const ITEM_HEIGHT = 32;
	const OVERSCAN = 10;

	let listScrollTop = 0;
	let listContainer;
	let listViewportHeight = 288;

	const trackListViewport = (node: HTMLElement) => {
		const updateHeight = () => {
			listViewportHeight = node.clientHeight || 288;
		};

		updateHeight();

		if (!('ResizeObserver' in window)) {
			return { destroy() {} };
		}

		const observer = new ResizeObserver(updateHeight);
		observer.observe(node);

		return {
			destroy() {
				observer.disconnect();
			}
		};
	};

	$: visibleStart = Math.max(0, Math.floor(listScrollTop / ITEM_HEIGHT) - OVERSCAN);
	$: visibleEnd = Math.min(
		filteredItems.length,
		Math.ceil((listScrollTop + listViewportHeight) / ITEM_HEIGHT) + OVERSCAN
	);
</script>

<svelte:window on:pointerdown={handlePointerDown} on:keydown={handleKeydown} />

<div class="relative w-full">
	<button
		bind:this={triggerElement}
		class="focus-ring relative w-full {($settings?.highContrastMode ?? false)
			? ''
			: 'outline-hidden focus:outline-hidden'}"
		aria-label={selectedModel
			? $i18n.t('Selected model: {{modelName}}', { modelName: triggerLabel })
			: placeholder}
		aria-haspopup="listbox"
		aria-expanded={show}
		id="model-selector-{id}-button"
		type="button"
		{disabled}
		on:click={toggleOpen}
	>
		<div
			class="flex w-full min-w-0 text-left px-0.5 bg-transparent {triggerClassName} justify-between {($settings?.highContrastMode ??
			false)
				? 'dark:placeholder-gray-100 placeholder-gray-800'
				: 'placeholder-gray-400'}"
			on:mouseenter={async () => {
				models.set(await getModels(localStorage.token));
			}}
		>
			<span class="min-w-0 flex-1 truncate">{triggerLabel}</span>
			<ChevronDown className="ml-1 size-2.5 shrink-0 self-center" strokeWidth="2.5" />
		</div>
	</button>

	{#if show}
		<div
			use:portal
			bind:this={contentElement}
			style="position: fixed; z-index: 9999; top: 0; left: 0; width: max-content;"
		>
			<div
				class="z-40 {className ??
					'w-[20rem]'} max-w-[calc(100vw-1rem)] justify-start rounded-xl border border-gray-100 bg-white p-0.5 shadow-lg outline-hidden dark:border-gray-800 dark:bg-gray-850 dark:text-white flex flex-col overflow-hidden"
				transition:flyAndScale
			>
				<slot>
					{#if searchEnabled}
						<div class="my-0.5 flex ml-2 mr-0.5 h-[1.6875rem] shrink-0 items-center gap-2">
							<Search className=" size-3.5 shrink-0" strokeWidth="2" />

							<input
								id="model-search-input"
								bind:value={searchValue}
								class="w-full bg-transparent text-[0.8125rem] font-normal outline-hidden placeholder:text-gray-400 dark:placeholder:text-gray-500"
								placeholder={searchPlaceholder}
								autocomplete="off"
								aria-label={$i18n.t('Search In Models')}
								on:keydown={(e) => {
									if (e.code === 'Enter') {
										if (filteredItems[selectedModelIdx]) {
											selectItem(filteredItems[selectedModelIdx], selectedModelIdx);
										}
										return; // dont need to scroll on selection
									} else if (e.code === 'ArrowDown') {
										e.stopPropagation();
										selectedModelIdx = Math.min(
											selectedModelIdx + 1,
											Math.max(filteredItems.length - 1, 0)
										);
									} else if (e.code === 'ArrowUp') {
										e.stopPropagation();
										selectedModelIdx = Math.max(selectedModelIdx - 1, 0);
									} else {
										// if the user types something, reset to the top selection.
										selectedModelIdx = 0;
									}

									const item = document.querySelector(`[data-arrow-selected="true"]`);
									item?.scrollIntoView({
										block: 'center',
										inline: 'nearest',
										behavior: 'instant'
									});
								}}
							/>

							{#if modelFilterItems.length > 0 || (multipleEnabled && items.length > 0)}
								<div class="flex min-w-0 shrink-0 items-center gap-0.5">
									{#if multipleEnabled && items.length > 0}
										<Tooltip content={$i18n.t('Compare')}>
											<button
												type="button"
												class="focus-ring flex size-[1.375rem] shrink-0 items-center justify-center rounded-lg transition-colors duration-100 {compareEnabled
													? ($settings?.highContrastMode ?? false)
														? 'bg-gray-200 text-gray-900 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-100 dark:hover:bg-gray-800'
														: 'bg-gray-50 text-gray-700 hover:bg-gray-50 dark:bg-gray-800/60 dark:text-gray-200 dark:hover:bg-gray-800/60'
													: ($settings?.highContrastMode ?? false)
														? 'text-gray-700 hover:bg-gray-200 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100'
														: 'text-gray-500 hover:bg-gray-50/40 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800/40 dark:hover:text-gray-100'}"
												aria-label={$i18n.t('Compare')}
												aria-pressed={compareEnabled}
												on:click={() => {
													setCompareEnabled(!compareEnabled);
												}}
											>
												<Keyframes className="size-3" strokeWidth="2" />
											</button>
										</Tooltip>
									{/if}

									{#if modelFilterItems.length > 0}
										<TagSelector
											bind:value={selectedFilter}
											placeholder={$i18n.t('All')}
											align="end"
											items={modelFilterItems}
											triggerClass="relative flex h-[1.375rem] max-w-32 items-center gap-0.5 rounded-xl bg-transparent px-1.5 text-[0.6875rem] font-normal transition-colors duration-100 {($settings?.highContrastMode ??
											false)
												? 'text-gray-700 hover:bg-gray-200 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-gray-100'
												: 'text-gray-500 hover:bg-gray-50/40 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800/40 dark:hover:text-gray-100'}"
											itemClass="flex h-[1.6875rem] w-full cursor-pointer items-center gap-2 rounded-xl bg-transparent px-2 text-[0.8125rem] capitalize {($settings?.highContrastMode ??
											false)
												? 'hover:bg-gray-200 hover:text-gray-900 dark:hover:bg-gray-800 dark:hover:text-gray-100'
												: 'hover:bg-gray-50/40 hover:text-gray-900 dark:hover:bg-gray-800/40 dark:hover:text-gray-100'}"
											contentClass="min-w-36 model-selector-child-menu"
											onChange={setModelFilter}
										/>
									{/if}
								</div>
							{/if}
						</div>
					{/if}

					<div class="group relative flex min-h-0 flex-1 flex-col">
						{#if filteredItems.length === 0}
							{#if items.length === 0 && $user?.role === 'admin'}
								<div
									class="my-2 flex w-full flex-col items-start justify-center px-4 py-3 text-start"
								>
									<div
										class="mb-0.5 text-xs font-normal leading-4 text-gray-800 dark:text-gray-100"
									>
										{$i18n.t('No models available')}
									</div>
									<div class="w-full text-[0.6875rem] leading-3.5 text-gray-500 dark:text-gray-400">
										{$i18n.t('Connect to an AI provider to start chatting')}
									</div>
									<button
										type="button"
										class="focus-ring mt-3 rounded-lg px-0 py-1 text-[0.6875rem] font-normal leading-none text-gray-600 underline-offset-2 transition-colors duration-100 hover:text-gray-800 hover:underline focus:outline-hidden focus:underline dark:text-gray-300 dark:hover:text-gray-100"
										on:click={() => {
											show = false;
											showSettings.set('admin:connections');
										}}
									>
										{$i18n.t('Manage Connections')}
									</button>
								</div>
							{:else}
								<div class="">
									<div
										class="flex min-h-8 items-center rounded-xl px-2 text-[0.8125rem] text-gray-700 dark:text-gray-100"
									>
										{$i18n.t('No results found')}
									</div>
								</div>
							{/if}
						{:else}
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<div
								class="min-h-0 flex-1 overflow-y-auto"
								style="max-height: 18rem;"
								role="listbox"
								aria-label={$i18n.t('Available models')}
								bind:this={listContainer}
								use:trackListViewport
								on:scroll={() => {
									listScrollTop = listContainer.scrollTop;
								}}
							>
								<div style="height: {visibleStart * ITEM_HEIGHT}px;" />
								{#each filteredItems.slice(visibleStart, visibleEnd) as item, i (item.value)}
									{@const index = visibleStart + i}
									<ModelItem
										{selectedModelIdx}
										{item}
										{index}
										value={primaryValue}
										{pinModelHandler}
										{selectionOnly}
										{compareEnabled}
										{selectedValues}
										onClick={() => {
											selectItem(item, index);
										}}
									/>
								{/each}
								<div style="height: {(filteredItems.length - visibleEnd) * ITEM_HEIGHT}px;" />
							</div>
						{/if}
					</div>

					{#if showSetDefault}
						<div class="flex shrink-0 items-center justify-end px-2 py-1 leading-none">
							<button
								type="button"
								class="focus-ring text-[0.65rem] font-normal leading-none text-gray-500 underline-offset-2 transition-colors duration-100 hover:text-gray-700 hover:underline dark:text-gray-500 dark:hover:text-gray-300"
								on:click|stopPropagation={setDefaultHandler}
							>
								{$i18n.t('Set as default')}
							</button>
						</div>
					{:else}
						<div class="shrink-0 pb-1"></div>
					{/if}

					<div class="hidden w-[42rem]" />
					<div class="hidden w-[28rem]" />
					<div class="hidden w-[24rem]" />
					<div class="hidden w-[22rem]" />
					<div class="hidden w-[20rem]" />
				</slot>
			</div>
		</div>
	{/if}
</div>
