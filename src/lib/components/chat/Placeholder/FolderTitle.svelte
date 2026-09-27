<script lang="ts">
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');

	import DOMPurify from 'dompurify';

	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { toast } from 'svelte-sonner';

	import { selectedFolder } from '$lib/stores';

	import { getFolderById, updateFolderById } from '$lib/apis/folders';
	import { getChatsByFolderId } from '$lib/apis/chats';

	import FolderModal from '$lib/components/layout/Sidebar/Folders/FolderModal.svelte';
	import FolderShareModal from '$lib/components/layout/Sidebar/Folders/FolderShareModal.svelte';

	import Folder from '$lib/components/icons/Folder.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import FolderMenu from '$lib/components/layout/Sidebar/Folders/FolderMenu.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import Emoji from '$lib/components/common/Emoji.svelte';
	import EmojiPicker from '$lib/components/common/EmojiPicker.svelte';

	export let folder = null;
	export let readOnly: boolean = false;

	export let onUpdate: Function = (folderId) => {};

	let showFolderModal = false;
	let showShareModal = false;

	const updateHandler = async ({ name, meta, data }) => {
		if (name === '') {
			toast.error($i18n.t('Project name cannot be empty.'));
			return;
		}

		const currentName = folder.name;

		name = name.trim();
		folder.name = name;

		const res = await updateFolderById(localStorage.token, folder.id, {
			name,
			...(meta ? { meta } : {}),
			...(data ? { data } : {})
		}).catch((error) => {
			toast.error(`${error}`);

			folder.name = currentName;
			return null;
		});

		if (res) {
			folder.name = name;
			if (data) {
				folder.data = { ...(folder.data ?? {}), ...data };
			}

			toast.success($i18n.t('Project updated successfully'));

			const _folder = await getFolderById(localStorage.token, folder.id).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			const updatedFolder = { ...folder, ..._folder };
			await selectedFolder.set(updatedFolder);
			onUpdate(updatedFolder);
		}
	};

	const updateIconHandler = async (iconName) => {
		const res = await updateFolderById(localStorage.token, folder.id, {
			meta: {
				icon: iconName ?? ''
			}
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			folder.meta = { ...folder.meta, icon: iconName ?? '' };

			toast.success($i18n.t('Project updated successfully'));

			const _folder = await getFolderById(localStorage.token, folder.id).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			const updatedFolder = { ...folder, ..._folder };
			await selectedFolder.set(updatedFolder);
			onUpdate(updatedFolder);
		}
	};

	const exportHandler = async () => {
		const chats = await getChatsByFolderId(localStorage.token, folder.id).catch((error) => {
			toast.error(`${error}`);
			return null;
		});
		if (!chats) {
			return;
		}

		const blob = new Blob([JSON.stringify(chats)], {
			type: 'application/json'
		});

		saveAs(blob, `project-${folder.name}-export-${Date.now()}.json`);
	};
</script>

{#if folder}
	<FolderModal
		bind:show={showFolderModal}
		edit={true}
		folderId={folder.id}
		onSubmit={updateHandler}
	/>

	<FolderShareModal bind:show={showShareModal} {folder} />

	<div class="mb-3 px-6 @md:max-w-3xl justify-between w-full flex relative group items-center">
		<div class="text-center flex gap-3.5 items-center">
			{#if readOnly}
				<div
					class="rounded-full bg-gray-50 dark:bg-gray-800 size-11 flex justify-center items-center"
				>
					{#if folder?.meta?.icon}
						<Emoji className="size-6" shortCode={folder.meta.icon} />
					{:else}
						<Folder className="size-4.5" strokeWidth="2" />
					{/if}
				</div>
			{:else}
				<EmojiPicker
					onClose={() => {}}
					selected={folder?.meta?.icon ?? null}
					onSubmit={(name) => {
						console.log(name);
						updateIconHandler(name);
					}}
				>
					<button
						aria-label={$i18n.t('Change project icon')}
						class="rounded-full bg-gray-50 dark:bg-gray-800 size-11 flex justify-center items-center outline-hidden focus:outline-hidden"
					>
						{#if folder?.meta?.icon}
							<Emoji className="size-6" shortCode={folder.meta.icon} />
						{:else}
							<Folder className="size-4.5" strokeWidth="2" />
						{/if}
					</button>
				</EmojiPicker>
			{/if}

			<div class="text-3xl line-clamp-1">
				{folder.name}
			</div>
		</div>

		{#if !readOnly}
			<div class="flex items-center translate-x-2.5">
				<FolderMenu
					align="end"
					onEdit={() => {
						showFolderModal = true;
					}}
					onShare={() => {
						showShareModal = true;
					}}
					onExport={() => {
						exportHandler();
					}}
				>
					<button
						class="p-1.5 dark:hover:bg-gray-850 rounded-full touch-auto"
						aria-label={$i18n.t('Project options')}
						on:click={(e) => {}}
					>
						<EllipsisHorizontal className="size-4" strokeWidth="2.5" />
					</button>
				</FolderMenu>
			</div>
		{/if}
	</div>
{/if}
