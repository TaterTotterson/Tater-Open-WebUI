export type TaterActivityAnimation = 'fade' | 'matrix' | 'ghost';

export type TaterThemeOption = {
	id: string;
	name: string;
	description: string;
	colors: [string, string, string];
};

export const TATER_THEME_OPTIONS: TaterThemeOption[] = [
	{
		id: 'system',
		name: 'System',
		description: 'Follow this device’s light or dark appearance.',
		colors: ['#f4f4f5', '#71717a', '#18181b']
	},
	{
		id: 'tater',
		name: 'Tater',
		description: 'The original roasted orange Tater look.',
		colors: ['#d65a1f', '#f08345', '#202225']
	},
	{
		id: 'tater-light',
		name: 'Tater Light',
		description: 'Warm orange on cream and soft-white surfaces.',
		colors: ['#c8531d', '#fffaf3', '#eadbca']
	},
	{
		id: 'blueberry',
		name: 'Blueberry',
		description: 'Clear blue accents with a cool navy surface.',
		colors: ['#4285f4', '#70b7ff', '#1b2635']
	},
	{
		id: 'mint',
		name: 'Mint',
		description: 'Fresh teal-green accents and forest shadows.',
		colors: ['#32b58d', '#67d6b1', '#182923']
	},
	{
		id: 'grape',
		name: 'Grape',
		description: 'Rich violet accents with deep plum panels.',
		colors: ['#9b6cf4', '#c18aff', '#292036']
	},
	{
		id: 'strawberry',
		name: 'Strawberry',
		description: 'Warm rose accents with berry-toned surfaces.',
		colors: ['#e75f91', '#ff8fb6', '#30202a']
	},
	{
		id: 'dark',
		name: 'Dark',
		description: 'The neutral Open WebUI dark appearance.',
		colors: ['#737373', '#262626', '#171717']
	},
	{
		id: 'oled-dark',
		name: 'OLED Dark',
		description: 'Pure black surfaces for OLED displays.',
		colors: ['#525252', '#101010', '#000000']
	},
	{
		id: 'light',
		name: 'Light',
		description: 'The neutral Open WebUI light appearance.',
		colors: ['#525252', '#f5f5f5', '#ffffff']
	}
];

const TATER_COLOR_THEMES = new Set([
	'tater',
	'tater-light',
	'blueberry',
	'mint',
	'grape',
	'strawberry'
]);

const THEME_META_COLORS: Record<string, string> = {
	tater: '#111213',
	'tater-light': '#f6f1e8',
	blueberry: '#0b1019',
	mint: '#0a1210',
	grape: '#120e19',
	strawberry: '#160e13',
	dark: '#171717',
	'oled-dark': '#000000',
	light: '#ffffff',
	her: '#983724'
};

const INLINE_GRAY_VARIABLES = [
	'--color-gray-800',
	'--color-gray-850',
	'--color-gray-900',
	'--color-gray-950'
];

export const normalizeActivityAnimation = (value: unknown): TaterActivityAnimation =>
	value === 'matrix' || value === 'ghost' ? value : 'fade';

export const isDarkInterfaceTheme = (theme: string, systemPrefersDark = false) =>
	theme === 'system'
		? systemPrefersDark
		: theme !== 'light' && theme !== 'tater-light' && theme !== 'her';

export const applyInterfaceTheme = (selectedTheme: string) => {
	if (typeof window === 'undefined') return;

	const root = document.documentElement;
	const theme = selectedTheme || 'system';
	const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
	const mode = isDarkInterfaceTheme(theme, systemTheme === 'dark') ? 'dark' : 'light';

	root.classList.remove('dark', 'light', 'her');
	INLINE_GRAY_VARIABLES.forEach((variable) => root.style.removeProperty(variable));

	if (theme === 'her') root.classList.add('her');
	root.classList.add(mode);

	if (TATER_COLOR_THEMES.has(theme)) {
		root.dataset.taterTheme = theme;
	} else {
		delete root.dataset.taterTheme;
	}

	if (theme === 'oled-dark') {
		root.style.setProperty('--color-gray-800', '#101010');
		root.style.setProperty('--color-gray-850', '#050505');
		root.style.setProperty('--color-gray-900', '#000000');
		root.style.setProperty('--color-gray-950', '#000000');
	}

	const metaThemeColor = document.querySelector('meta[name="theme-color"]');
	metaThemeColor?.setAttribute(
		'content',
		theme === 'system' ? THEME_META_COLORS[systemTheme] : (THEME_META_COLORS[theme] ?? '#171717')
	);

	const applyTheme = (window as Window & { applyTheme?: () => void }).applyTheme;
	if (typeof applyTheme === 'function') applyTheme();
};
