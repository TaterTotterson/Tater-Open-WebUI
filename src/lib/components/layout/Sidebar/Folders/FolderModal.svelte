<script lang="ts">
	import { getContext, createEventDispatcher, onMount, tick } from 'svelte';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Modal from '$lib/components/common/Modal.svelte';
	import XMark from '../icons/XMark.svelte';

	import { toast } from 'svelte-sonner';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { user } from '$lib/stores';

	import Textarea from '$lib/components/common/Textarea.svelte';
	import {
		getAvailableProjectDirectories,
		getFolderById,
		type ProjectDirectory
	} from '$lib/apis/folders';
	const i18n = getContext('i18n');

	export let show = false;
	export let onSubmit: Function = (e) => {};

	export let folderId = null;
	export let parentId = null;
	export let edit = false;

	let folder = null;
	let name = '';
	let meta = {
		background_image_url: null
	};
	let data = {
		system_prompt: ''
	};
	let projectPath = '';
	let creationMode: 'new' | 'existing' = 'new';
	let availableProjects: ProjectDirectory[] = [];
	let selectedExistingProject = '';
	let loadingAvailableProjects = false;

	let loading = false;

	const submitHandler = async () => {
		loading = true;

		await onSubmit({
			name,
			meta,
			data: {
				...data,
				...(creationMode === 'existing' && !edit
					? { existing_project_name: selectedExistingProject }
					: {})
			},
			parent_id: edit ? undefined : parentId
		});
		show = false;
		loading = false;
	};

	const init = async () => {
		if (folderId) {
			folder = await getFolderById(localStorage.token, folderId).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			name = folder.name;
			meta = folder.meta || {
				background_image_url: null
			};
			data = { system_prompt: folder.data?.system_prompt ?? '' };
			projectPath = folder.data?.project_path ?? '';
		} else {
			loadingAvailableProjects = true;
			availableProjects = await getAvailableProjectDirectories(localStorage.token).catch(
				(error) => {
					toast.error(`${error}`);
					return [];
				}
			);
			loadingAvailableProjects = false;
		}

		focusInput();
	};

	const focusInput = async () => {
		await tick();
		const input = document.getElementById('folder-name') as HTMLInputElement;
		if (input) {
			input.focus();
			input.select();
		}
	};

	$: if (show) {
		init();
	}

	$: if (!show && !edit) {
		name = '';
		creationMode = 'new';
		selectedExistingProject = '';
		availableProjects = [];
		meta = {
			background_image_url: null
		};
		data = {
			system_prompt: ''
		};
	}
</script>

<Modal size="md" bind:show>
	<div>
		<div class=" flex justify-between dark:text-gray-300 px-4 pt-3 pb-1">
			<div class=" text-sm self-center">
				{#if edit}
					{$i18n.t('Edit Project')}
				{:else}
					{$i18n.t('Create Project')}
				{/if}
			</div>
			<button
				aria-label={$i18n.t('Close')}
				class="self-center rounded-lg p-1 text-gray-500 transition hover:bg-gray-50 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
				on:click={() => {
					show = false;
				}}
			>
				<XMark className={'size-4'} />
			</button>
		</div>

		<div class="flex flex-col md:flex-row w-full px-4 pb-4 md:space-x-4 dark:text-gray-200">
			<div class=" flex flex-col w-full sm:flex-row sm:justify-center sm:space-x-6">
				<form
					class="flex flex-col w-full"
					on:submit|preventDefault={() => {
						submitHandler();
					}}
				>
					{#if !edit}
						<div
							class="mb-3 grid grid-cols-2 gap-1 rounded-xl bg-gray-100/70 p-1 dark:bg-gray-800/50"
						>
							<button
								type="button"
								class="rounded-lg px-3 py-1.5 text-xs transition {creationMode === 'new'
									? 'bg-white text-gray-800 shadow-sm dark:bg-gray-700 dark:text-gray-100'
									: 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'}"
								on:click={() => {
									creationMode = 'new';
									selectedExistingProject = '';
									name = '';
								}}
							>
								{$i18n.t('New Folder')}
							</button>
							<button
								type="button"
								class="rounded-lg px-3 py-1.5 text-xs transition {creationMode === 'existing'
									? 'bg-white text-gray-800 shadow-sm dark:bg-gray-700 dark:text-gray-100'
									: 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'}"
								on:click={() => {
									creationMode = 'existing';
									name = selectedExistingProject;
								}}
							>
								{$i18n.t('Existing Folder')}
							</button>
						</div>
					{/if}

					<div class="flex flex-col w-full mt-1">
						<div class=" mb-1 text-xs text-gray-500">
							{creationMode === 'existing' && !edit
								? $i18n.t('Project Folder')
								: $i18n.t('Project Name')}
						</div>

						<div class="flex-1">
							{#if creationMode === 'existing' && !edit}
								<select
									id="folder-name"
									class="w-full rounded-lg border border-gray-200 bg-transparent px-2.5 py-2 text-sm outline-none dark:border-gray-700"
									bind:value={selectedExistingProject}
									disabled={loadingAvailableProjects}
									on:change={() => (name = selectedExistingProject)}
								>
									<option value="" disabled>
										{loadingAvailableProjects
											? $i18n.t('Looking for project folders…')
											: $i18n.t('Select a folder in /projects')}
									</option>
									{#each availableProjects as project (project.path)}
										<option value={project.name}>{project.name}</option>
									{/each}
								</select>
								{#if !loadingAvailableProjects && availableProjects.length === 0}
									<div class="mt-2 text-xs text-gray-500">
										{$i18n.t('Every folder in /projects is already linked to a project.')}
									</div>
								{/if}
							{:else}
								<input
									id="folder-name"
									class="w-full text-sm bg-transparent placeholder:text-gray-300 dark:placeholder:text-gray-700 outline-hidden"
									type="text"
									bind:value={name}
									placeholder={$i18n.t('Enter project name')}
									autocomplete="off"
								/>
							{/if}
						</div>
					</div>

					{#if edit && projectPath}
						<div class="mt-2 text-xs text-gray-500">
							<div>{$i18n.t('Project Directory')}</div>
							<div
								class="mt-1 truncate font-mono text-gray-700 dark:text-gray-300"
								title={projectPath}
							>
								{projectPath}
							</div>
						</div>
					{/if}

					<input
						id="folder-background-image-input"
						type="file"
						hidden
						accept="image/*"
						on:change={(e) => {
							const inputFiles = e.target.files;

							let reader = new FileReader();
							reader.onload = (event) => {
								let originalImageUrl = `${event.target.result}`;
								meta.background_image_url = originalImageUrl;
							};

							if (
								inputFiles &&
								inputFiles.length > 0 &&
								['image/gif', 'image/webp', 'image/jpeg', 'image/png'].includes(
									inputFiles[0]['type']
								)
							) {
								reader.readAsDataURL(inputFiles[0]);
							} else {
								console.log(`Unsupported File Type '${inputFiles[0]['type']}'.`);

								// clear the input
								e.target.value = '';
							}
						}}
					/>

					<div class="flex justify-between w-full mt-1 items-center">
						<div class="text-xs text-gray-500">{$i18n.t('Project Background Image')}</div>

						<div class="">
							<button
								aria-labelledby="chat-background-label background-image-url-state"
								class="p-1 px-3 text-xs flex rounded-sm transition"
								on:click={() => {
									if (meta?.background_image_url !== null) {
										meta.background_image_url = null;
									} else {
										const input = document.getElementById('folder-background-image-input');
										if (input) {
											input.click();
										}
									}
								}}
								type="button"
							>
								<span class="ml-2 self-center" id="background-image-url-state"
									>{(meta?.background_image_url ?? null) === null
										? $i18n.t('Upload')
										: $i18n.t('Reset')}</span
								>
							</button>
						</div>
					</div>

					<hr class=" border-gray-50 dark:border-gray-850/30 my-2.5 w-full" />

					{#if $user?.role === 'admin' || ($user?.permissions.chat?.system_prompt ?? true)}
						<div class="my-1">
							<div class="mb-2 text-xs text-gray-500">{$i18n.t('System Prompt')}</div>
							<div>
								<Textarea
									className=" text-sm w-full bg-transparent outline-hidden "
									placeholder={$i18n.t(
										'Write your model system prompt content here\ne.g.) You are Mario from Super Mario Bros, acting as an assistant.'
									)}
									maxSize={200}
									bind:value={data.system_prompt}
								/>
							</div>
						</div>
					{/if}

					<div class="flex justify-end pt-3 text-sm font-normal gap-1.5">
						<button
							class="px-3.5 py-1.5 text-sm font-normal bg-black hover:bg-gray-950 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full flex flex-row space-x-1 items-center {loading
								? ' cursor-not-allowed'
								: ''}"
							type="submit"
							disabled={loading || (creationMode === 'existing' && !selectedExistingProject)}
						>
							{$i18n.t('Save')}

							{#if loading}
								<div class="ml-2 self-center">
									<Spinner />
								</div>
							{/if}
						</button>
					</div>
				</form>
			</div>
		</div>
	</div>
</Modal>
