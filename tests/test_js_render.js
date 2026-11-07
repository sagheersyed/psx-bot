const http = require('http');

http.get('http://127.0.0.1:5000/api/low_float', (res) => {
    let raw = '';
    res.on('data', chunk => raw += chunk);
    res.on('end', () => {
        const data = JSON.parse(raw);
        console.log('Stocks received:', data.stocks.length);
        let errorCount = 0;
        data.stocks.forEach(s => {
            try {
                const isLock = s.phase_code === 'UPPER_LOCK';
                const isBreakout = s.phase_code === 'BREAKOUT';
                const isAccum = s.phase_code === 'ACCUMULATION';
                const isDist = s.phase_code === 'DISTRIBUTION';

                let borderTheme = 'border-gray-800 hover:border-gray-700';
                if (isLock) borderTheme = 'border-purple-600/70 glow-purple';
                else if (isBreakout) borderTheme = 'border-amber-500/70 glow-amber';
                else if (isAccum) borderTheme = 'border-emerald-500/70 glow-green';
                else if (isDist) borderTheme = 'border-red-600/70 glow-red';

                let phaseBadgeClass = 'bg-dark-950 text-gray-400 border-gray-800';
                if (isLock) phaseBadgeClass = 'bg-purple-950 text-purple-300 border-purple-700 animate-pulse';
                else if (isBreakout) phaseBadgeClass = 'bg-amber-950 text-amber-300 border-amber-700';
                else if (isAccum) phaseBadgeClass = 'bg-emerald-950 text-emerald-300 border-emerald-700';
                else if (isDist) phaseBadgeClass = 'bg-red-950 text-red-300 border-red-700';

                const turnoverWidth = Math.min(Math.max(s.float_turnover_pct * 3.5, 4), 100);
                const turnoverColor = s.float_turnover_pct >= 15 ? 'bg-amber-400' : (s.float_turnover_pct >= 3.0 ? 'bg-emerald-400' : 'bg-gray-600');

                const html = `
                    <div>
                        ${s.symbol} ${s.sector} ${s.name} ${s.price.toFixed(2)} ${s.change_pct}
                        ${s.syndicate_phase} ${s.season_badge}
                        ${(s.float_shares / 1000).toLocaleString(undefined, {maximumFractionDigits:0})}
                        ${s.volume.toLocaleString()} ${s.vol_surge_x} ${s.float_turnover_pct}
                        ${s.actionable_insight}
                    </div>
                `;
            } catch (err) {
                console.error('JS ERROR on:', s.symbol, err);
                errorCount++;
            }
        });
        console.log('Finished testing JS template string. Errors:', errorCount);
    });
});
