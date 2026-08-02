import os, sys
os.environ['MPLBACKEND'] = 'Agg'

import pyEDM
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
os.environ['MPLCONFIGDIR'] = os.path.join(os.getcwd(), '.matplotlib_cache')
import matplotlib.pyplot as plt
plt.rcParams['axes.unicode_minus'] = False

def main():
    print('='*60)
    print('pyEDM Demo')
    print('='*60)
    print('Data: pandas DataFrame, col1=time, col2+=vars')

    print('Built-in datasets:')
    for name in sorted(pyEDM.sampleData.keys()):
        d = pyEDM.sampleData[name]
        print(f'  {name:25s}  shape={d.shape}')

    df = pyEDM.sampleData['block_3sp']
    print(f'\nUsing block_3sp, columns={list(df.columns)}')

    print('\n=== Step 1: EmbedDimension ===')
    rho_E = pyEDM.EmbedDimension(dataFrame=df, lib='1 100', pred='101 198',
                                  maxE=10, Tp=1, columns='x_t', target='x_t',
                                  showPlot=False, numProcess=1)
    best_E = int(rho_E.loc[rho_E['rho'].idxmax(), 'E'])
    print(f'Best E = {best_E}')
    print(rho_E.to_string(index=False))

    print('\n=== Step 2: Simplex ===')
    sx = pyEDM.Simplex(dataFrame=df, lib='1 100', pred='101 198',
                        E=best_E, Tp=1, columns='x_t', target='x_t',
                        showPlot=False)
    obs = sx['Observations']
    pred = sx['Predictions']
    r = obs.corr(pred)
    err = pyEDM.ComputeError(obs, pred)
    print(f'rho={r:.4f}, MAE={err["MAE"]:.4f}, RMSE={err["RMSE"]:.4f}')

    print('\n=== Step 3: S-Map ===')
    for th in [0, 1, 2, 3, 4, 6, 8]:
        try:
            s = pyEDM.SMap(dataFrame=df, lib='1 100', pred='101 198',
                           E=best_E, Tp=1, columns='x_t', target='x_t',
                           theta=th, showPlot=False)
            pred_s = s['predictions']['Predictions']
            obs_s = s['predictions']['Observations']
            print(f'  theta={th:4.1f} -> rho={obs_s.corr(pred_s):.4f}')
        except Exception as e:
            print(f'  theta={th:4.1f} -> error: {e}')

    print('\n=== Step 4: CCM ===')
    ccm_xy = pyEDM.CCM(dataFrame=df, E=best_E, Tp=0,
                        columns='x_t', target='y_t',
                        libSizes='10 190 20', sample=100, showPlot=False)
    ccm_yx = pyEDM.CCM(dataFrame=df, E=best_E, Tp=0,
                        columns='y_t', target='x_t',
                        libSizes='10 190 20', sample=100, showPlot=False)
    print('x->y:')
    print(ccm_xy.to_string(index=False))
    print('\ny->x:')
    print(ccm_yx.to_string(index=False))

    print('\n=== Step 5: Plot ===')
    fig, axes = plt.subplots(3, 2, figsize=(14, 10))
    fig.suptitle('pyEDM Empirical Dynamic Modeling Demo', fontsize=14)

    axes[0,0].plot(df['time'], df['x_t'], label='x_t')
    axes[0,0].plot(df['time'], df['y_t'], label='y_t')
    axes[0,0].plot(df['time'], df['z_t'], label='z_t')
    axes[0,0].set_title('Time Series')
    axes[0,0].legend()
    axes[0,0].grid(True, alpha=0.3)

    axes[0,1].plot(rho_E['E'], rho_E['rho'], 'o-', color='steelblue')
    axes[0,1].axvline(best_E, color='red', ls='--', label=f'Best E={best_E}')
    axes[0,1].set_title('EmbedDimension Search')
    axes[0,1].legend()
    axes[0,1].grid(True, alpha=0.3)

    axes[1,0].plot(sx['Time'], obs, label='Observed', alpha=0.8)
    axes[1,0].plot(sx['Time'], pred, label='Predicted', alpha=0.8)
    axes[1,0].set_title(f'Simplex Prediction (rho={r:.3f})')
    axes[1,0].legend()
    axes[1,0].grid(True, alpha=0.3)

    axes[1,1].scatter(obs, pred, alpha=0.6, s=20, c='steelblue')
    axes[1,1].plot([-3,3], [-3,3], 'r--', alpha=0.5)
    axes[1,1].set_aspect('equal')
    axes[1,1].grid(True, alpha=0.3)

    axes[2,0].plot(ccm_yx['LibSize'], ccm_yx['y_t:x_t'], 'o-', color='seagreen', label='y_t -> x_t')
    axes[2,0].plot(ccm_xy['LibSize'], ccm_xy['x_t:y_t'], 'o-', color='coral', label='x_t -> y_t')
    axes[2,0].set_title('CCM Convergence')
    axes[2,0].legend()
    axes[2,0].grid(True, alpha=0.3)

    axes[2,1].axis('off')
    txt = ('Best E = {}\nSimplex rho = {:.3f}\n'
           'CCM x_t->y_t = {:.3f}\n'
           'CCM y_t->x_t = {:.3f}').format(
            best_E, r,
            ccm_xy['x_t:y_t'].iloc[-1],
            ccm_yx['y_t:x_t'].iloc[-1])
    axes[2,1].text(0.05, 0.5, txt, fontsize=10, family='monospace',
                   verticalalignment='center')

    plt.tight_layout()
    out_path = 'edm_demo_results.png'
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print(f'\nSaved plot: {out_path}')
    plt.close()

if __name__ == '__main__':
    main()
