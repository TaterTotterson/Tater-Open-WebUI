<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import type { TaterActivityAnimation } from '$lib/utils/taterAppearance';

	export let text = '';
	export let mode: TaterActivityAnimation = 'fade';

	type CharacterState = {
		actual: string;
		display: string;
		delay: number;
		settled: boolean;
	};

	const MATRIX_GLYPHS = Array.from('ﾊﾐﾋｰｳｼﾅﾓﾆｻﾜﾂｵﾘｱﾎﾃﾏｹﾒｴｶｷﾑﾕﾗｾﾈｽ01<>/*+=#');
	let characters: CharacterState[] = Array.from(text).map((actual) => ({
		actual,
		display: actual,
		delay: 0,
		settled: true
	}));
	let active = false;
	let interval: ReturnType<typeof setInterval> | null = null;
	let animationFrame: number | null = null;

	const seededValue = (index: number, salt = 0) => {
		let value = 2166136261 ^ salt;
		for (let offset = 0; offset < text.length; offset += 1) {
			value ^= text.charCodeAt(offset) + index * 31;
			value = Math.imul(value, 16777619);
		}
		return (value >>> 0) / 4294967295;
	};

	const shuffledVisibleIndexes = () => {
		const indexes = characters
			.map((character, index) => ({ character, index }))
			.filter(({ character }) => !/\s/.test(character.actual))
			.map(({ index }) => index);
		return indexes.sort((left, right) => seededValue(left, 17) - seededValue(right, 17));
	};

	const stopAnimation = () => {
		if (interval) clearInterval(interval);
		if (animationFrame !== null) cancelAnimationFrame(animationFrame);
		interval = null;
		animationFrame = null;
	};

	const showFinalText = () => {
		characters = Array.from(text).map((actual) => ({
			actual,
			display: actual,
			delay: 0,
			settled: true
		}));
		active = true;
	};

	const startGhostReveal = () => {
		const order = shuffledVisibleIndexes();
		const rank = new Map(order.map((index, position) => [index, position]));
		const divisor = Math.max(1, order.length - 1);
		characters = characters.map((character, index) => ({
			...character,
			display: character.actual,
			delay: /\s/.test(character.actual) ? 0 : Math.round(((rank.get(index) ?? 0) / divisor) * 230),
			settled: true
		}));
		active = false;
		animationFrame = requestAnimationFrame(() => {
			animationFrame = requestAnimationFrame(() => {
				active = true;
			});
		});
	};

	const startMatrixReveal = () => {
		const order = shuffledVisibleIndexes();
		const rank = new Map(order.map((index, position) => [index, position]));
		const divisor = Math.max(1, order.length - 1);
		const settleTimes = characters.map((character, index) =>
			/\s/.test(character.actual)
				? 0
				: 105 + Math.round(((rank.get(index) ?? 0) / divisor) * 285 + seededValue(index, 41) * 35)
		);
		const startedAt = performance.now();
		let frame = 0;

		characters = characters.map((character, index) => ({
			...character,
			display: /\s/.test(character.actual)
				? character.actual
				: MATRIX_GLYPHS[Math.floor(seededValue(index, 71) * MATRIX_GLYPHS.length)],
			settled: /\s/.test(character.actual)
		}));

		interval = setInterval(() => {
			frame += 1;
			const elapsed = performance.now() - startedAt;
			let unfinished = false;
			characters = characters.map((character, index) => {
				if (character.settled || elapsed >= settleTimes[index]) {
					return { ...character, display: character.actual, settled: true };
				}
				unfinished = true;
				return {
					...character,
					display:
						MATRIX_GLYPHS[Math.floor(seededValue(index + frame * 13, 97) * MATRIX_GLYPHS.length)]
				};
			});
			if (!unfinished) stopAnimation();
		}, 38);
	};

	onMount(() => {
		if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
			showFinalText();
			return;
		}
		if (mode === 'matrix') startMatrixReveal();
		else if (mode === 'ghost') startGhostReveal();
		else active = true;
	});

	onDestroy(stopAnimation);
</script>

{#if mode === 'fade'}
	<span class="activity-text" in:fade={{ duration: 220 }} out:fade={{ duration: 100 }}>{text}</span>
{:else}
	<span class="activity-text character-reveal {mode}" class:active>
		<span class="sr-only">{text}</span>
		<span aria-hidden="true">
			{#each characters as character}
				{#if character.actual === '\n'}
					<br />
				{:else if /\s/.test(character.actual)}
					<span>{character.actual === ' ' ? '\u00a0' : character.actual}</span>
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
		white-space: pre-wrap;
	}

	.character-reveal {
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

	.ghost .character-face {
		opacity: 0;
		filter: blur(5px);
		transform: translateY(2px) scale(0.98);
	}

	.ghost.active .character-face {
		opacity: 1;
		filter: blur(0);
		transform: translateY(0) scale(1);
		transition:
			opacity 180ms ease-out var(--character-delay),
			filter 210ms ease-out var(--character-delay),
			transform 210ms ease-out var(--character-delay);
	}

	@media (prefers-reduced-motion: reduce) {
		.ghost .character-face,
		.ghost.active .character-face {
			opacity: 1;
			filter: none;
			transform: none;
			transition: none;
		}
	}
</style>
