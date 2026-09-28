<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		getTaterTask,
		getTaterTaskHistory,
		type TaterTaskDetail,
		type TaterTaskHistoryItem
	} from '$lib/apis/tater';
	import { mobile, showControls, socket } from '$lib/stores';
	import { onDestroy, onMount } from 'svelte';

	import Markdown from './Messages/Markdown.svelte';

	export let chatId: string | null = null;

	let tasks: TaterTaskHistoryItem[] = [];
	let loading = true;
	let error = '';
	let query = '';
	let expandedTaskId: string | null = null;
	let taskDetails: Record<string, TaterTaskDetail> = {};
	let detailLoadingTaskId: string | null = null;
	let hasMore = false;
	let loadingMore = false;
	let socketInstance: any = null;
	const PAGE_SIZE = 50;

	$: normalizedQuery = query.trim().toLocaleLowerCase();
	$: filteredTasks = normalizedQuery
		? tasks.filter((task) =>
				[task.title, task.parent_chat_title, task.prompt_preview, task.output_preview, task.status]
					.filter(Boolean)
					.some((value) => String(value).toLocaleLowerCase().includes(normalizedQuery))
			)
		: tasks;

	const loadHistory = async ({ quiet = false } = {}) => {
		if (!quiet) loading = true;
		error = '';
		try {
			tasks = await getTaterTaskHistory(localStorage.token, PAGE_SIZE, 0);
			hasMore = tasks.length === PAGE_SIZE;
		} catch (loadError) {
			error = `${loadError}`;
		} finally {
			loading = false;
		}
	};

	const loadMore = async () => {
		if (loadingMore || !hasMore) return;
		loadingMore = true;
		try {
			const nextTasks = await getTaterTaskHistory(localStorage.token, PAGE_SIZE, tasks.length);
			tasks = [...tasks, ...nextTasks.filter((task) => !tasks.some((item) => item.id === task.id))];
			hasMore = nextTasks.length === PAGE_SIZE;
		} catch (loadError) {
			error = `${loadError}`;
		} finally {
			loadingMore = false;
		}
	};

	const toggleTask = async (task: TaterTaskHistoryItem) => {
		if (expandedTaskId === task.id) {
			expandedTaskId = null;
			return;
		}

		expandedTaskId = task.id;
		if (taskDetails[task.id]) return;
		detailLoadingTaskId = task.id;
		try {
			taskDetails = {
				...taskDetails,
				[task.id]: await getTaterTask(localStorage.token, task.id)
			};
		} catch (loadError) {
			error = `${loadError}`;
		} finally {
			detailLoadingTaskId = null;
		}
	};

	const taskEventHandler = async (event: any) => {
		if (event?.data?.type === 'tater:tasks') {
			await loadHistory({ quiet: true });
		}
	};

	const timestamp = (value: number | null) => {
		if (!value) return '';
		return new Intl.DateTimeFormat(undefined, {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		}).format(value * 1000);
	};

	const duration = (task: TaterTaskHistoryItem) => {
		if (!task.started_at || !task.finished_at) return '';
		const seconds = Math.max(0, task.finished_at - task.started_at);
		if (seconds < 60) return `${seconds}s`;
		const minutes = Math.floor(seconds / 60);
		const remainingSeconds = seconds % 60;
		return remainingSeconds ? `${minutes}m ${remainingSeconds}s` : `${minutes}m`;
	};

	const statusClasses = (status: TaterTaskHistoryItem['status']) => {
		if (status === 'completed') {
			return 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300';
		}
		if (status === 'cancelled') {
			return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
		}
		return 'bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300';
	};

	const openPath = async (path: string) => {
		await goto(path);
		if ($mobile) showControls.set(false);
	};

	onMount(async () => {
		socketInstance = $socket;
		socketInstance?.on('events', taskEventHandler);
		await loadHistory();
	});

	onDestroy(() => {
		socketInstance?.off('events', taskEventHandler);
	});
</script>

<div class="flex h-full min-h-0 flex-col bg-white dark:bg-gray-900">
	<div class="shrink-0 border-b border-gray-100 px-3 pb-3 pt-1 dark:border-gray-800/70">
		<div class="flex items-start justify-between gap-3">
			<div>
				<h2 class="text-sm font-medium text-gray-800 dark:text-gray-100">Task history</h2>
				<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
					Review finished work from every chat.
				</p>
			</div>
			<button
				type="button"
				class="flex size-8 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
				on:click={() => loadHistory()}
				aria-label="Refresh task history"
				title="Refresh task history"
			>
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					class="size-4"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M16.023 9.348h4.992V4.356m-.97 4.021A8.25 8.25 0 1 0 21.75 12M3.955 15.623A8.25 8.25 0 0 0 12 20.25c2.04 0 3.907-.74 5.348-1.968"
					/>
				</svg>
			</button>
		</div>

		{#if tasks.length > 0}
			<div class="relative mt-3">
				<svg
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					class="pointer-events-none absolute left-2.5 top-2.5 size-4 text-gray-400"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="m21 21-4.35-4.35m1.35-5.4a6.75 6.75 0 1 1-13.5 0 6.75 6.75 0 0 1 13.5 0Z"
					/>
				</svg>
				<input
					bind:value={query}
					class="w-full rounded-xl border border-gray-200 bg-transparent py-2 pl-8 pr-3 text-sm text-gray-800 outline-none transition placeholder:text-gray-400 focus:border-amber-400 dark:border-gray-700 dark:text-gray-100 dark:focus:border-amber-500"
					placeholder="Search tasks, chats, or results"
				/>
			</div>
		{/if}
	</div>

	<div class="min-h-0 flex-1 overflow-y-auto px-3 py-3 scrollbar-hidden">
		{#if loading}
			<div class="space-y-2" aria-label="Loading task history">
				{#each Array(4) as _}
					<div class="animate-pulse rounded-2xl border border-gray-100 p-3 dark:border-gray-800">
						<div class="h-3.5 w-2/3 rounded bg-gray-100 dark:bg-gray-800"></div>
						<div class="mt-2 h-3 w-1/2 rounded bg-gray-100 dark:bg-gray-800"></div>
					</div>
				{/each}
			</div>
		{:else if error}
			<div
				class="rounded-2xl border border-red-100 bg-red-50/60 p-4 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-300"
			>
				<p>Task history could not be loaded.</p>
				<p class="mt-1 break-words text-xs opacity-80">{error}</p>
				<button
					type="button"
					class="mt-3 font-medium underline underline-offset-2"
					on:click={() => loadHistory()}
				>
					Try again
				</button>
			</div>
		{:else if tasks.length === 0}
			<div class="flex h-full min-h-48 flex-col items-center justify-center px-5 text-center">
				<div
					class="flex size-10 items-center justify-center rounded-2xl bg-amber-50 text-amber-600 dark:bg-amber-950/30 dark:text-amber-400"
				>
					<svg
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						class="size-5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
						/>
					</svg>
				</div>
				<p class="mt-3 text-sm font-medium text-gray-700 dark:text-gray-200">
					No finished tasks yet
				</p>
				<p class="mt-1 max-w-56 text-xs leading-5 text-gray-500 dark:text-gray-400">
					Completed, failed, and cancelled tasks will be kept here for review.
				</p>
			</div>
		{:else if filteredTasks.length === 0}
			<p class="py-10 text-center text-sm text-gray-500 dark:text-gray-400">No matching tasks.</p>
		{:else}
			<div class="space-y-2">
				{#each filteredTasks as task (task.id)}
					{@const expanded = expandedTaskId === task.id}
					{@const elapsed = duration(task)}
					{@const detail = taskDetails[task.id]}
					<div
						class="overflow-hidden rounded-2xl border transition {task.parent_chat_id === chatId
							? 'border-amber-200 bg-amber-50/20 dark:border-amber-900/60 dark:bg-amber-950/10'
							: 'border-gray-100 bg-white dark:border-gray-800 dark:bg-gray-900'}"
					>
						<div class="flex items-start gap-2.5 p-3">
							<span
								class="mt-1 flex size-5 shrink-0 items-center justify-center rounded-full {task.status ===
								'completed'
									? 'text-emerald-600 dark:text-emerald-400'
									: task.status === 'cancelled'
										? 'text-gray-400'
										: 'text-red-500'}"
							>
								{#if task.status === 'completed'}
									<svg
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="2"
										class="size-4"
										><path stroke-linecap="round" stroke-linejoin="round" d="m5 12 4 4L19 6" /></svg
									>
								{:else}
									<svg
										viewBox="0 0 24 24"
										fill="none"
										stroke="currentColor"
										stroke-width="1.75"
										class="size-4"
										><path
											stroke-linecap="round"
											stroke-linejoin="round"
											d="M6 18 18 6M6 6l12 12"
										/></svg
									>
								{/if}
							</span>

							<button
								type="button"
								class="min-w-0 flex-1 text-left"
								on:click={() => toggleTask(task)}
								aria-expanded={expanded}
							>
								<span
									class="block break-words text-sm font-medium leading-5 text-gray-800 dark:text-gray-100"
									>{task.title}</span
								>
								<span
									class="mt-1 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[0.6875rem] text-gray-500 dark:text-gray-400"
								>
									<span
										class="rounded-full px-1.5 py-0.5 font-medium capitalize {statusClasses(
											task.status
										)}">{task.status}</span
									>
									<span class="truncate"
										>{task.parent_chat_title ??
											(task.parent_chat_id
												? 'Source chat unavailable'
												: 'Unknown source chat')}</span
									>
									{#if elapsed}<span aria-hidden="true">·</span><span>{elapsed}</span>{/if}
								</span>
								{#if !expanded && task.output_preview}
									<span
										class="mt-2 line-clamp-2 block text-xs leading-5 text-gray-500 dark:text-gray-400"
										>{task.output_preview}</span
									>
								{/if}
							</button>

							<button
								type="button"
								class="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg text-gray-400 transition hover:bg-gray-100 dark:hover:bg-gray-800"
								on:click={() => toggleTask(task)}
								aria-label={expanded ? 'Collapse task' : 'Expand task'}
							>
								<svg
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.5"
									class="size-4 transition {expanded ? 'rotate-180' : ''}"
									><path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6" /></svg
								>
							</button>
						</div>

						{#if expanded}
							<div class="border-t border-gray-100 px-3 pb-3 pt-3 dark:border-gray-800">
								<div
									class="flex flex-wrap gap-x-3 gap-y-1 text-[0.6875rem] text-gray-500 dark:text-gray-400"
								>
									<span>{timestamp(task.finished_at ?? task.updated_at)}</span>
									{#if task.capabilities.length > 0}<span>{task.capabilities.join(' + ')}</span
										>{/if}
								</div>

								{#if detail?.prompt || task.prompt_preview}
									<div class="mt-3">
										<p
											class="text-[0.6875rem] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500"
										>
											Request
										</p>
										<p
											class="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-gray-700 dark:text-gray-300"
										>
											{detail?.prompt ?? task.prompt_preview}
										</p>
									</div>
								{/if}

								<div class="mt-3">
									<p
										class="text-[0.6875rem] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500"
									>
										Result
									</p>
									{#if detailLoadingTaskId === task.id}
										<p class="mt-1 animate-pulse text-xs text-gray-500 dark:text-gray-400">
											Loading saved output…
										</p>
									{:else if detail?.output}
										<div
											class="mt-1 break-words text-xs leading-5 text-gray-700 dark:text-gray-300"
										>
											<Markdown
												id={`task-history-${task.id}`}
												content={detail.output}
												compactPreview={true}
												editCodeBlock={false}
											/>
										</div>
									{:else}
										<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">
											No written result was saved.
										</p>
									{/if}
								</div>

								<div class="mt-3 flex flex-wrap gap-2">
									<button
										type="button"
										class="rounded-lg bg-gray-100 px-2.5 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
										on:click={() => openPath(`/tasks/${task.id}`)}
									>
										View task
									</button>
									{#if task.parent_chat_id && task.parent_chat_title}
										<button
											type="button"
											class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-amber-700 transition hover:bg-amber-50 dark:text-amber-300 dark:hover:bg-amber-950/30"
											on:click={() => openPath(`/c/${task.parent_chat_id}`)}
										>
											Open source chat
										</button>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{/each}
				{#if hasMore && !normalizedQuery}
					<button
						type="button"
						class="mt-3 w-full rounded-xl py-2 text-xs font-medium text-gray-500 transition hover:bg-gray-100 hover:text-gray-700 disabled:opacity-60 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
						on:click={loadMore}
						disabled={loadingMore}
					>
						{loadingMore ? 'Loading…' : 'Load older tasks'}
					</button>
				{/if}
			</div>
		{/if}
	</div>
</div>
