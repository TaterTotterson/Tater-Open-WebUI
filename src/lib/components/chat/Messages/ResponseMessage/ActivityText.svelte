<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import type { TaterActivityAnimation } from '$lib/utils/taterAppearance';

	export let text = '';
	export let mode: TaterActivityAnimation = 'fade';
	export let incremental = false;
	export let block = false;
	export let compact = false;

	type CharacterState = {
		id: number;
		actual: string;
		display: string;
		delay: number;
		settled: boolean;
		settleAt: number;
	};

	const MATRIX_GLYPHS = Array.from('ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽ01<>/*+=#');
	const GHOST_LETTERS = Array.from(
		'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
	);
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

	const stopCharacterAnimation = () => {
		if (matrixInterval) clearInterval(matrixInterval);
		matrixInterval = null;
	};

	const updateAnimatedCharacters = () => {
		matrixFrame += 1;
		const now = performance.now();
		let unfinished = false;
		characters = characters.map((character, index) => {
			if (character.settled || now >= character.settleAt) {
				return { ...character, display: character.actual, settled: true };
			}
			unfinished = true;
			if (mode === 'ghost') return character;
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
		if (!unfinished) stopCharacterAnimation();
	};

	const ensureCharacterAnimation = () => {
		if (matrixInterval || !characters.some((character) => !character.settled)) return;
		matrixInterval = setInterval(updateAnimatedCharacters, 38);
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
			const delay = whitespace ? 0 : Math.round(seededValue(actual, index, 17) * 190);
			const glyph = (mode === 'matrix' || mode === 'ghost') && !whitespace && !reducedMotion;
			const glyphs = mode === 'ghost' ? GHOST_LETTERS : MATRIX_GLYPHS;
			return {
				id: nextCharacterId++,
				actual,
				display: glyph
					? glyphs[Math.floor(seededValue(actual, index, 71) * glyphs.length)]
					: actual,
				delay,
				settled: !glyph,
				settleAt: glyph
					? now +
						(mode === 'ghost' ? 190 : 105) +
						delay +
						Math.round(seededValue(actual, index, 41) * 120)
					: 0
			};
		});

		characters = [...preserved, ...additions];
		currentText = nextText;
		currentMode = mode;
		if ((mode === 'matrix' || mode === 'ghost') && !reducedMotion) ensureCharacterAnimation();
		else stopCharacterAnimation();
	};

	onMount(() => {
		mounted = true;
		reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		syncCharacters(text, true);
	});

	$: if (mounted && (text !== currentText || mode !== currentMode)) {
		syncCharacters(text, mode !== currentMode);
	}

	onDestroy(stopCharacterAnimation);
</script>

{#if mode === 'fade' && !incremental}
	<span
		class="activity-text"
		class:block
		class:compact
		in:fade={{ duration: 220 }}
		out:fade={{ duration: 100 }}>{text}</span
	>
{:else}
	<span
		class="activity-text character-reveal {mode}"
		class:block
		class:incremental
		class:compact
		aria-label={text}
	>
		<span class="animated-copy" aria-hidden="true">
			{#each characters as character (character.id)}
				{#if character.actual === '\n'}
					<br />
				{:else if /\s/.test(character.actual)}
					<span class="activity-space">{character.actual}</span>
				{:else}
					<span
						class="activity-character"
						class:settled={character.settled}
						style={`--character-delay: ${character.delay}ms`}
					>
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

	.activity-text.compact {
		display: block;
		width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.character-reveal:not(.block):not(.compact),
	.animated-copy {
		display: inline;
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

	.ghost .activity-character:not(.settled) .character-face {
		animation: ghost-glyph-in 180ms ease-out var(--character-delay) both;
	}

	.ghost .activity-character.settled .character-face {
		animation: ghost-letter-in 130ms ease-out both;
	}

	@keyframes character-fade-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	@keyframes ghost-glyph-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 0.55;
		}
	}

	@keyframes ghost-letter-in {
		from {
			opacity: 0.55;
		}
		to {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.fade.incremental .character-face,
		.ghost .activity-character .character-face {
			animation: none;
		}
	}
</style>
