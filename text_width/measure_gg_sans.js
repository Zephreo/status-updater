// Rebuilds gg_sans_metrics.json, the font measurements text_width/__init__.py uses.
//
// Open https://discord.com/login (no need to sign in), paste this into the browser's
// devtools console, and paste the copied text over gg_sans_metrics.json. The login page
// declares Discord's fonts, so this measures exactly what the client draws messages with.
(async () => {
    const weights = ['400', '700'];  // Regular and **bold**
    const extraChars = '‘’“”–—…•·€™';
    await Promise.all([
        ...weights.map(w => document.fonts.load(`${w} 1000px "gg sans"`, 'a')),
        document.fonts.load('400 1000px "gg mono"', 'a'),
    ]);

    const ascii = [];
    for (let c = 32; c <= 126; c++) ascii.push(String.fromCharCode(c));
    const chars = [...ascii];
    for (let c = 0xA0; c <= 0xFF; c++) chars.push(String.fromCharCode(c));
    chars.push(...extraChars);

    const ctx = document.createElement('canvas').getContext('2d');
    ctx.fontKerning = 'normal';
    ctx.font = '400 1000px "gg mono"';
    const monoWidth = Math.round(ctx.measureText('a').width);

    const lines = [
        '{',
        '"font": "gg sans",',
        '"source": "Measured in Discord\'s web client with canvas measureText at 1000px, see measure_gg_sans.js",',
        '"units_per_em": 1000,',
        '"chars": "Widths are for ASCII 32-126, then U+00A0-U+00FF, then extra_chars",',
        `"extra_chars": ${JSON.stringify(extraChars)},`,
        `"mono_width": ${monoWidth},`,
        '"weights": {',
    ];
    weights.forEach((weight, wi) => {
        ctx.font = `${weight} 1000px "gg sans"`;
        const width = text => ctx.measureText(text).width;
        const widths = Object.fromEntries(chars.map(c => [c, width(c)]));
        // Kerning between ASCII pairs, grouped by left character then amount: {"A": {"-100": "TY"}}
        const kerning = {};
        for (const left of ascii) for (const right of ascii) {
            const amount = Math.round(width(left + right) - widths[left] - widths[right]);
            if (amount) ((kerning[left] ??= {})[amount] ??= []).push(right);
        }
        lines.push(`"${weight}": {`, `"widths": [${chars.map(c => Math.round(widths[c])).join(',')}],`, '"kerning": {');
        const lefts = Object.entries(kerning);
        lefts.forEach(([left, byAmount], i) => {
            const amounts = Object.entries(byAmount).map(([amount, rights]) => `"${amount}": ${JSON.stringify(rights.join(''))}`);
            lines.push(`${JSON.stringify(left)}: {${amounts.join(', ')}}${i < lefts.length - 1 ? ',' : ''}`);
        });
        lines.push('}', `}${wi < weights.length - 1 ? ',' : ''}`);
    });
    lines.push('}', '}', '');

    const text = lines.join('\n');
    JSON.parse(text);  // Check it's valid before copying
    copy(text);
    console.log(`Copied ${text.length} characters`);
    return text;
})();
