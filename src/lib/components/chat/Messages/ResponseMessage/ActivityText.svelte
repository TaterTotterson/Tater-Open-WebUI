<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import type { TaterActivityAnimation } from '$lib/utils/taterAppearance';

	export let text = '';
	export let mode: TaterActivityAnimation = 'fade';
	export let incremental = false;
	export let block = false;

	type CharacterState = {
		id: number;
		actual: string;
		display: string;
		delay: number;
		settled: boolean;
		settleAt: number;
	};

	const MATRIX_GLYPHS = Array.from('ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽ01<>/*+=#');
	let nextCharacterId = 1;
	let characters: CharacterState[] = Array.from(text).map((actual) => ({
		id: nextCharacterId++,
		actual,
		display: actual,
		delay: 0,
		settled: true,
		settleAt: 0
	}));
	let currentText = text;
	let currentMode = mode;
	let mounted = false;
	let reducedMotion = true;
	let matrixInterval: ReturnType<typeof setInterval> | null = null;
	let matrixFrame = 0;

	const seededValue = (value: string, index: number, salt = 0) => {
		let hash = 2166136261 ^ salt;
		for (let offset = 0; offset < value.length; offset += 1) {
			hash ^= value.charCodeAt(offset) + index * 31;
			hash = Math.imul(hash, 16777619);
		}
		return (hash >>> 0) / 4294967295;
	};

	const stopMatrixAnimation = () => {
		if (matrixInterval) clearInterval(matrixInterval);
		matrixInterval = null;
	};

	const updateMatrixCharacters = () => {
		matrixFrame += 1;
		const now = performance.now();
		let unfinished = false;
		characters = characters.map((character, index) => {
			if (character.settled || now >= character.settleAt) {
				return { ...character, display: character.actual, settled: true };
			}
			unfinished = true;
			return {
				...character,
				display:
					MATRIX_GLYPHS[
						Math.floor(
							seededValue(character.actual, index + matrixFrame * 13, 97) * MATRIX_GLYPHS.length
						)
					]
			};
		});
		if (!unfinished) stopMatrixAnimation();
	};

	const ensureMatrixAnimation = () => {
		if (matrixInterval || !characters.some((character) => !character.settled)) return;
		matrixInterval = setInterval(updateMatrixCharacters, 38);
	};

	const matchingPrefixLength = (left: string[], right: string[]) => {
		let length = 0;
		while (length < left.length && length < right.length && left[length] === right[length]) {
			length += 1;
		}
		return length;
	};

	const syncCharacters = (nextText: string, force = false) => {
		const nextCharacters = Array.from(nextText);
		const previousCharacters = Array.from(currentText);
		const prefixLength =
			incremental && !force ? matchingPrefixLength(previousCharacters, nextCharacters) : 0;
		const preserved = characters.slice(0, prefixLength);
		const now = typeof performance === 'undefined' ? 0 : performance.now();
		const additions = nextCharacters.slice(prefixLength).map((actual, offset) => {
			const index = prefixLength + offset;
			const whitespace = /\s/.test(actual);
			const delay = whitespace ? 0 : Math.round(seededValue(nextText, index, 17) * 190);
			const matrix = mode === 'matrix' && !whitespace && !reducedMotion;
			return {
				id: nextCharacterId++,
				actual,
				display: matrix
					? MATRIX_GLYPHS[Math.floor(seededValue(actual, index, 71) * MATRIX_GLYPHS.length)]
					: actual,
				delay,
				settled: !matrix,
				settleAt: matrix
					? now + 105 + delay + Math.round(seededValue(nextText, index, 41) * 120)
					: 0
			};
		});

		characters = [...preserved, ...additions];
		currentText = nextText;
		currentMode = mode;
		if (mode === 'matrix' && !reducedMotion) ensureMatrixAnimation();
		else stopMatrixAnimation();
	};

	onMount(() => {
		mounted = true;
		reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		syncCharacters(text, true);
	});

	$: if (mounted && (text !== currentText || mode !== currentMode)) {
		syncCharacters(text, mode !== currentMode);
	}

	onDestroy(stopMatrixAnimation);
</script>

{#if mode === 'fade' && !incremental}
	<span class="activity-text" class:block in:fade={{ duration: 220 }} out:fade={{ duration: 100 }}
		>{text}</span
	>
{:else}
	<span class="activity-text character-reveal {mode}" class:block class:incremental>
		<span class="screen-reader-copy">{text}</span>
		<span class="animated-copy" aria-hidden="true">
			{#each characters as character (character.id)}
				{#if character.actual === '\n'}
					<br />
				{:else if /\s/.test(character.actual)}
					<span class="activity-space">{character.actual}</span>
				{:else}
					<span class="activity-character" style={`--character-delay: ${character.delay}ms`}>
						<span class="character-measure">{character.actual}</span>
						<span class="character-face">{character.display}</span>
					</span>
				{/if}
			{/each}
		</span>
	</span>
{/if}

<style>
	.activity-text {
		min-width: 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}

	.activity-text.block {
		display: block;
		width: 100%;
	}

	.character-reveal:not(.block),
	.animated-copy {
		display: inline;
	}

	.screen-reader-copy {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	.activity-character {
		display: inline-grid;
		vertical-align: baseline;
	}

	.character-measure,
	.character-face {
		grid-area: 1 / 1;
	}

	.character-measure {
		visibility: hidden;
	}

	.character-face {
		color: inherit;
		font: inherit;
	}

	.fade.incremental .character-face {
		animation: character-fade-in 190ms ease-out var(--character-delay) both;
	}

	.ghost .character-face {
		animation: character-ghost-in 230ms ease-out var(--character-delay) both;
	}

	@keyframes character-fade-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	@keyframes character-ghost-in {
		from {
			opacity: 0;
			filter: blur(5px);
			transform: translateY(2px) scale(0.98);
		}
		to {
			opacity: 1;
			filter: blur(0);
			transform: translateY(0) scale(1);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.fade.incremental .character-face,
		.ghost .character-face {
			animation: none;
		}
	}
</style>
