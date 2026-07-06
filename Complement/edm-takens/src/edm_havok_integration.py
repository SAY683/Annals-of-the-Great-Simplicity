import os
os.environ['MPLBACKEND'] = 'Agg'
os.environ['MPLCONFIGDIR'] = os.path.join(os.getcwd(), '.matplotlib_cache')
import numpy as np
import pyEDM
import warnings

def havok_decompose(data, embed_dim, rank=None):
    """HAVOK (Hankel DMD / Koopman) decomposition of a time series."""
    n, m = len(data), embed_dim
    if rank is None:
        rank = m - 1
    N = n - m + 1
    H = np.zeros((N, m))
    for i in range(m):
        H[:, i] = data[i:i+N]
    U, s, Vt = np.linalg.svd(H, full_matrices=False)
    V = Vt.T
    V_r = V[:, :rank]
    X, Xp = V_r[:-1, :].T, V_r[1:, :].T
    K = Xp @ np.linalg.pinv(X)
    forcing = V[1:, rank] if rank < m else np.zeros(N - 1)
    explained_var = np.sum(s[:rank]**2) / np.sum(s**2)
    return {'K': K, 'singular_values': s, 'forcing': forcing, 'V': V,
            'rank': rank, 'embed_dim': embed_dim, 'explained_var': explained_var}

def edm_guided_havok(df, target_col, lib=None, pred=None, max_E=10):
    """Use EDM's EmbedDimension to determine optimal E, then run HAVOK."""
    rho_E = pyEDM.EmbedDimension(
        dataFrame=df, lib=lib, pred=pred,
        maxE=max_E, Tp=1, columns=target_col, target=target_col,
        showPlot=False, numProcess=1)
    optimal_E = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])

    smap = pyEDM.PredictNonlinear(
        dataFrame=df, lib=lib, pred=pred,
        E=optimal_E, columns=target_col, target=target_col,
        showPlot=False)
    rho_0 = smap.loc[smap['theta'] == smap['theta'].min(), 'rho'].values[0]
    rho_max = smap['rho'].max()
    theta_best = smap.loc[smap['rho'].idxmax(), 'theta']
    is_nonlinear = (rho_max - rho_0) >= 0.05 and theta_best > smap['theta'].min()

    data = df[target_col].values
    havok = havok_decompose(data, embed_dim=optimal_E)
    forcing = havok['forcing']
    forcing_var_ratio = np.var(forcing) / (np.var(data[:len(forcing)]) + 1e-10)
    spike_threshold = np.percentile(np.abs(forcing), 90)
    spike_indices = np.where(np.abs(forcing) > spike_threshold)[0]

    return {
        'optimal_E': optimal_E, 'is_nonlinear': is_nonlinear,
        'theta_best': theta_best, 'rho_theta_0': rho_0,
        'rho_smap_max': rho_max,
        'havok': havok, 'forcing_var_ratio': forcing_var_ratio,
        'spike_count': len(spike_indices),
        'spike_indices': spike_indices.tolist(),
        'spike_threshold': spike_threshold, 'smap': smap
    }

if __name__ == '__main__':
    os.makedirs('.matplotlib_cache', exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    df = pyEDM.sampleData['block_3sp']
    R = edm_guided_havok(df, 'x_t', lib='1 100', pred='101 198')

    print('=== EDM + HAVOK Integrated Analysis ===')
    print(f"Optimal E (from EDM) = {R['optimal_E']}")
    print(f"Nonlinear? = {R['is_nonlinear']} (theta={R['theta_best']:.1f})")
    print(f"Forcing variance ratio = {R['forcing_var_ratio']:.2%}")
    print(f"Top-10% forcing spike count = {R['spike_count']}")

    d = R['havok']
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))
    fig.suptitle(f'EDM + HAVOK: Nonlinear Diagnostics (E={R["optimal_E"]})', fontsize=14)

    axes[0].stem(range(1, len(d['singular_values'])+1), d['singular_values'], basefmt=' ')
    axes[0].axvline(R['optimal_E'] - 0.5, color='red', ls='--',
                    label=f'linear cutoff r={R["optimal_E"]-1}')
    axes[0].set_title('Singular Values (HAVOK)')
    axes[0].legend(); axes[0].grid(True, alpha=0.3)

    t = np.arange(len(d['forcing']))
    axes[1].fill_between(t, d['forcing'], alpha=0.3, color='coral')
    axes[1].plot(t, d['forcing'], 'o-', color='coral', markersize=3)
    axes[1].axhline(0, color='gray', alpha=0.3)
    axes[1].set_title('HAVOK Forcing Term (spikes = nonlinear events)')
    axes[1].set_ylabel('Forcing'); axes[1].grid(True, alpha=0.3)

    smap = R['smap']
    axes[2].plot(smap['theta'], smap['rho'], 'o-', color='darkgreen')
    axes[2].axvline(R['theta_best'], color='red', ls='--',
                    label=f"theta={R['theta_best']:.1f}")
    axes[2].set_title(f'S-Map (EDM) | System: {"Nonlinear" if R["is_nonlinear"] else "Linear"}')
    axes[2].legend(); axes[2].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig('edm_havok_integration.png', dpi=150)
    plt.close()
    print('Saved: edm_havok_integration.png')
