<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onDestroy, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Chat from '$lib/components/chat/Chat.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { getFolderById } from '$lib/apis/folders';
	import { selectedFolder } from '$lib/stores';

	let ready = false;

	onMount(async () => {
		const projectId = $page.params.projectId;
		if (!projectId) {
			await goto('/');
			return;
		}

		if ($selectedFolder?.id !== projectId) {
			const project = await getFolderById(localStorage.token, projectId).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (!project) {
				await goto('/');
				return;
			}

			await selectedFolder.set(project);
		}

		ready = true;
	});

	onDestroy(() => {
		selectedFolder.set(null);
	});
</script>

{#if ready}
	<Chat />
{:else}
	<div class="w-full h-screen flex items-center justify-center">
		<Spinner />
	</div>
{/if}
