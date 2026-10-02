<script lang="ts">
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import type { TaterTask } from '$lib/apis/tater';
	import { mobile, showSidebar } from '$lib/stores';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import XMark from './icons/XMark.svelte';

	const i18n: any = getContext('i18n');

	export let task: TaterTask;
	export let selected = false;
	export let onCancel: (task: TaterTask) => void | Promise<void> = () => {};

	let cancelling = false;
	$: isSelected = selected || $page.url.pathname === `/tasks/${task.id}`;

	const openTask = async () => {
		await goto(`/tasks/${task.id}`);
		if ($mobile) showSidebar.set(false);
	};

	const cancel = async (event: MouseEvent) => {
		event.preventDefault();
		event.stopPropagation();
		if (cancelling) return;
		cancelling = true;
		try {
			await onCancel(task);
		} finally {
			cancelling = false;
		}
	};
</script>

<div
	class="tater-task-row group flex min-w-0 items-center rounded-xl px-2 py-1.5 transition {isSelected
		? 'bg-black/[0.035] dark:bg-white/[0.045]'
		: 'hover:bg-gray-100 dark:hover:bg-gray-900'}"
>
	<button
		type="button"
		class="flex min-w-0 flex-1 items-center gap-2 text-left"
		on:click={openTask}
	>
		<span class="relative flex size-2 shrink-0">
			<span class="absolute inline-flex size-2 animate-ping rounded-full bg-amber-400 opacity-60"
			></span>
			<span class="relative inline-flex size-2 rounded-full bg-amber-500"></span>
		</span>
		<span class="min-w-0 flex-1">
			<span class="block truncate text-[0.8125rem] text-gray-700 dark:text-gray-300"
				>{task.title}</span
			>
			<span class="block truncate text-[0.6875rem] text-gray-400 dark:text-gray-600">
				{task.activity || task.status}
			</span>
		</span>
	</button>

	<Tooltip content={$i18n.t('Cancel task')} placement="right">
		<button
			type="button"
			class="flex size-6 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-gray-200 hover:text-gray-700 focus:opacity-100 dark:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-300 {$mobile
				? 'opacity-100'
				: 'opacity-0 group-hover:opacity-100'}"
			on:click={cancel}
			aria-label={$i18n.t('Cancel task')}
			disabled={cancelling}
		>
			<XMark className="size-3.5" strokeWidth="2" />
		</button>
	</Tooltip>
</div>
