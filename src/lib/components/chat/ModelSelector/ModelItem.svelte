<script lang="ts">
	import { marked } from 'marked';

	import { getContext, tick } from 'svelte';

	import { mobile, settings, user } from '$lib/stores';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { copyToClipboard, sanitizeResponseContent } from '$lib/utils';
	import { resolveLocalizedModelDescription } from '$lib/utils/localizedContent';
	import Check from '$lib/components/icons/Check.svelte';
	import ModelItemMenu from './ModelItemMenu.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import { toast } from 'svelte-sonner';
	import Tag from '$lib/components/icons/Tag.svelte';
	import Label from '$lib/components/icons/Label.svelte';

	const i18n = getContext('i18n');

	export let selectedModelIdx: number = -1;
	export let item: any = {};
	export let index: number = -1;
	export let value: string | null = '';
	export let selectedValues: string[] = [];
	export let compareEnabled = false;

	export let pinModelHandler: (modelId: string) => void = () => {};
	export let selectionOnly = false;

	export let onClick: () => void = () => {};

	$: localizedDescription = resolveLocalizedModelDescription(item.model, $i18n.language);

	const copyLinkHandler = async (model) => {
		const baseUrl = window.location.origin;
		const res = await copyToClipboard(`${baseUrl}/?model=${encodeURIComponent(model.id)}`);

		if (res) {
			toast.success($i18n.t('Copied link to clipboard'));
		} else {
			toast.error($i18n.t('Failed to copy link'));
		}
	};

	let showMenu = false;
	$: isSelected = compareEnabled ? selectedValues.includes(item.value) : value === item.value;
</script>

<button
	role="option"
	aria-selected={isSelected}
	aria-label={$i18n.t('Select {{modelName}} model', { modelName: item.label })}
	class="focus-ring group/item flex h-8 w-full cursor-pointer select-none items-center rounded-xl px-2 text-left text-[0.8125rem] font-normal text-gray-700 outline-hidden transition-colors duration-75 dark:text-gray-100 {($settings?.highContrastMode ??
	false)
		? 'hover:bg-gray-200 dark:hover:bg-gray-800'
		: 'hover:bg-gray-50/40 dark:hover:bg-gray-800/40'} {index === selectedModelIdx &&
	!compareEnabled
		? ($settings?.highContrastMode ?? false)
			? 'bg-gray-200 dark:bg-gray-800'
			: 'bg-gray-50/70 dark:bg-gray-800/60'
		: ''} {isSelected
		? ($settings?.highContrastMode ?? false)
			? 'bg-gray-200 dark:bg-gray-800'
			: 'bg-gray-50/70 dark:bg-gray-800/60'
		: ''}"
	data-arrow-selected={index === selectedModelIdx}
	data-value={item.value}
	on:click={() => {
		onClick();
	}}
>
	<div class="flex flex-1 flex-col gap-1.5 overflow-hidden">
		<!-- {#if (item?.model?.tags ?? []).length > 0}
			<div
				class="flex gap-0.5 self-center items-start h-full w-full translate-y-[0.5px] overflow-x-auto scrollbar-none"
			>
				{#each item.model?.tags.sort((a, b) => a.name.localeCompare(b.name)) as tag}
					<Tooltip content={tag.name} className="flex-shrink-0">
						<div
							class=" text-xs font-normal px-1 rounded-sm uppercase bg-gray-500/20 text-gray-700 dark:text-gray-200"
						>
							{tag.name}
						</div>
					</Tooltip>
				{/each}
			</div>
		{/if} -->

		<div class="flex items-center gap-2 overflow-hidden">
			<div class="flex items-center min-w-fit">
				<Tooltip content={$user?.role === 'admin' ? (item?.value ?? '') : ''} placement="top-start">
					<img
						src={`${WEBUI_API_BASE_URL}/models/model/profile/image?id=${item.model.id}&lang=${$i18n.language}`}
						alt={$i18n.t('{{modelName}} profile image', { modelName: item.label })}
						class="flex size-4 items-center rounded-full"
						loading="lazy"
						on:error={(e) => {
							// LICENSE covers this Open WebUI fallback logo.
							// Do not alter, remove, obscure, or replace it except as LICENSE permits:
							// https://docs.openwebui.com/license.
							e.currentTarget.src = '/favicon.png';
						}}
					/>
				</Tooltip>
			</div>

			<div class="flex min-w-0 items-center">
				<Tooltip content={`${item.label} (${item.value})`} placement="top-start">
					<div class="line-clamp-1">
						{item.label}
					</div>
				</Tooltip>
			</div>

			<div class="flex shrink-0 items-center gap-1.5">
				<!-- {JSON.stringify(item.info)} -->

				{#if (item?.model?.tags ?? []).length > 0}
					{#key item.model.id}
						<Tooltip elementId="tags-{item.model.id}">
							<div slot="tooltip" id="tags-{item.model.id}">
								{#each item.model?.tags.sort((a, b) => a.name.localeCompare(b.name)) as tag}
									<Tooltip content={tag.name} className="flex-shrink-0">
										<div class=" text-xs font-normal rounded-sm uppercase text-white">
											{tag.name}
										</div>
									</Tooltip>
								{/each}
							</div>

							<div class="translate-y-[1px]">
								<Tag />
							</div>
						</Tooltip>
					{/key}
				{/if}

				{#if item.model.connection_type === 'external'}
					<Tooltip content={`${$i18n.t('External')}`}>
						<div class="translate-y-[1px]">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="size-3"
							>
								<path
									fill-rule="evenodd"
									d="M8.914 6.025a.75.75 0 0 1 1.06 0 3.5 3.5 0 0 1 0 4.95l-2 2a3.5 3.5 0 0 1-5.396-4.402.75.75 0 0 1 1.251.827 2 2 0 0 0 3.085 2.514l2-2a2 2 0 0 0 0-2.828.75.75 0 0 1 0-1.06Z"
									clip-rule="evenodd"
								/>
								<path
									fill-rule="evenodd"
									d="M7.086 9.975a.75.75 0 0 1-1.06 0 3.5 3.5 0 0 1 0-4.95l2-2a3.5 3.5 0 0 1 5.396 4.402.75.75 0 0 1-1.251-.827 2 2 0 0 0-3.085-2.514l-2 2a2 2 0 0 0 0 2.828.75.75 0 0 1 0 1.06Z"
									clip-rule="evenodd"
								/>
							</svg>
						</div>
					</Tooltip>
				{/if}

				{#if localizedDescription}
					<Tooltip
						content={`${marked.parse(
							sanitizeResponseContent(localizedDescription).replaceAll('\n', '<br>')
						)}`}
					>
						<div class=" translate-y-[1px]">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="w-4 h-4"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"
								/>
							</svg>
						</div>
					</Tooltip>
				{/if}
			</div>
		</div>
	</div>

	<div class="ml-auto flex shrink-0 items-center gap-1.5 pl-2">
		{#if !selectionOnly}
			<ModelItemMenu
				bind:show={showMenu}
				model={item.model}
				{pinModelHandler}
				copyLinkHandler={() => {
					copyLinkHandler(item.model);
				}}
			>
				<button
					aria-label={`${$i18n.t('More Options')}`}
					class="focus-ring flex"
					on:click={(e) => {
						e.preventDefault();
						e.stopPropagation();
						showMenu = !showMenu;
					}}
				>
					<EllipsisHorizontal />
				</button>
			</ModelItemMenu>
		{/if}

		{#if isSelected}
			<div>
				<Check className="size-3" />
			</div>
		{/if}
	</div>
</button>
