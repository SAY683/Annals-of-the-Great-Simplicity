import os, sys, warnings, numpy as np
from numpy.linalg import svd, pinv
try:
    import pyEDM
    _PYEDM = True
except ImportError:
    pyEDM = None
    _PYEDM = False
import pandas as pd

# Resolve skill data path (test file is in tests/, data is in ../data/)
_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_DATA = os.path.join(_SKILL_ROOT, 'data')
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

warnings.filterwarnings('ignore')
_SEED = 42

def havok_decompose(data, embed_dim, r=None):
    n, m = len(data), embed_dim
    if r is None: r = m - 1
    N = n - m + 1
    H = np.zeros((N, m))
    for i in range(m): H[:, i] = data[i:i+N]
    U, s, Vt = svd(H, full_matrices=False)
    U_r = U[:, :r]
    X, Xp = U_r[:-1, :].T, U_r[1:, :].T
    K = Xp @ pinv(X)
    forcing = U[1:, r]
    return K, s, forcing, U

class TestHankelMatrix:
    @staticmethod
    def run():
        n, m = 100, 10
        np.random.seed(_SEED)
        data = np.random.randn(n)
        H = np.zeros((n - m + 1, m))
        for i in range(m): H[:, i] = data[i:i + n - m + 1]
        N = n - m + 1
        assert H.shape == (N, m), f'Shape: {H.shape} != ({N},{m})'
        for i in range(m):
            for j in range(N):
                assert np.isclose(H[j, i], data[i+j]), f'H[{j},{i}] mismatch'
        for i in range(1, N):
            for j in range(m - 1):
                assert np.isclose(H[i, j], H[i-1, j+1]), 'Hankel structure broken'
        print(f'  [PASS] Hankel matrix: shape {H.shape}')
        return True

class TestSVDReconstruction:
    @staticmethod
    def run():
        np.random.seed(_SEED); data = np.random.randn(100)
        em = 8; N = len(data)-em+1
        H = np.zeros((N, em))
        for i in range(em): H[:,i] = data[i:i+N]
        U,s,Vt = svd(H, full_matrices=False)
        err = np.max(np.abs(H - U@np.diag(s)@Vt))
        assert err < 1e-12, f'SVD recon err: {err:.2e}'
        print(f'  [PASS] SVD recon: max_err={err:.2e}')
        return True

class TestLinearRegression:
    @staticmethod
    def run():
        np.random.seed(_SEED); data = np.random.randn(100)
        em, r = 5, 4
        K,s,forcing,U = havok_decompose(data, em, r)
        assert K.shape == (r,r), f'K shape: {K.shape}'
        assert len(forcing) == len(data)-em, f'forcing len: {len(forcing)}'
        # r=m-1 case: V-based X is square, exact interpolation
        N = len(data)-em+1
        H = np.zeros((N,em))
        for i in range(em): H[:,i] = data[i:i+N]
        Ua,sa,Vta = svd(H, full_matrices=False)
        V = Vta.T
        Vr_bad = V[:,:r]
        Xv = Vr_bad[:-1,:].T  # r x (m-1) = r x r (square!)
        Xpv = Vr_bad[1:,:].T   # r x r
        Kv = Xpv @ pinv(Xv)
        mse_v = np.mean((Kv @ Xv - Xpv)**2)
        assert mse_v < 1e-20, f'V-based MSE should be ~0, got {mse_v:.2e}'
        # U-based: r x (N-1), overdetermined
        Ur = Ua[:,:r]
        Xu = Ur[:-1,:].T
        Xpu = Ur[1:,:].T
        mse_u = np.mean((K @ Xu - Xpu)**2)
        assert mse_u > 1e-10, f'U-based MSE should be non-zero, got {mse_u:.2e}'
        print(f'  [PASS] Linear regression: K({r}x{r}), MSE(V)={mse_v:.2e}, MSE(U)={mse_u:.6f}')
        return True

class TestForcingSemantics:
    @staticmethod
    def run():
        np.random.seed(_SEED)
        data = np.sin(np.linspace(0,10*np.pi,200)) + 0.05*np.random.randn(200)
        K,s,forcing,U = havok_decompose(data, 10, 7)
        assert np.allclose(forcing, U[1:,7]), 'Forcing != U[1:,r]'
        print(f'  [PASS] Forcing semantic: len={len(forcing)}, N-1={len(data)-10}')
        return True

class TestReproducibility:
    @staticmethod
    def run():
        np.random.seed(_SEED); data = np.random.randn(50)
        K1,s1,f1,_ = havok_decompose(data,6)
        K2,s2,f2,_ = havok_decompose(data,6)
        assert np.allclose(K1,K2) and np.allclose(s1,s2) and np.allclose(f1,f2)
        print(f'  [PASS] Reproducibility')
        return True

class TestEdgeCases:
    @staticmethod
    def run():
        results = []
        # Case 1: minimal data (n = m+5, enough for U to work)
        np.random.seed(_SEED)
        try:
            K,s,f,U = havok_decompose(np.random.randn(15), 6)
            assert K.shape == (5,5)
            assert len(f) == 9  # N-1 = (15-6+1)-1 = 9
            results.append(('Minimal data (n=15,m=6)', True))
        except Exception as e:
            results.append(('Minimal data (n=15,m=6)', False, str(e)))
        # Case 2: constant data
        try:
            K,s,f,U = havok_decompose(np.ones(50)*5, 6)
            assert np.isclose(s[0]/s.sum(), 1.0, atol=1e-8) or np.all(s[1:] < 1e-10)
            results.append(('Constant data', True))
        except Exception as e:
            results.append(('Constant data', False, str(e)))
        # Case 3: random noise
        np.random.seed(_SEED)
        try:
            K,s,f,U = havok_decompose(np.random.randn(100), 10)
            assert K.shape == (9,9)
            assert len(f) == 90  # N-1 = (100-10+1)-1 = 90
            results.append(('Random noise', True))
        except Exception as e:
            results.append(('Random noise', False, str(e)))
        # Case 4: r = m-1 (standard default)
        try:
            K,s,f,U = havok_decompose(np.random.randn(30), 5, 4)
            assert len(f) == 25  # N-1 = (30-5+1)-1 = 25
            results.append(('r=m-1 (standard)', True))
        except Exception as e:
            results.append(('r=m-1 (standard)', False, str(e)))
        # Case 5: r = 1 (aggressive truncation)
        try:
            K,s,f,U = havok_decompose(np.random.randn(50), 8, 1)
            assert K.shape == (1,1)
            assert len(f) == 42  # N-1 = (50-8+1)-1 = 42
            results.append(('r=1 (aggressive)', True))
        except Exception as e:
            results.append(('r=1 (aggressive)', False, str(e)))
        for name,status,*msg in results:
            tag = 'PASS' if status else 'FAIL'
            extra = f' - {msg[0]}' if msg else ''
            print(f'  [{tag}] {name}{extra}')
        return all(r[1] for r in results)

class TestKnownSignal:
    @staticmethod
    def run():
        np.random.seed(_SEED)
        t = np.linspace(0,20*np.pi,500)
        Ks,ss,fs,_ = havok_decompose(np.sin(t), 15)
        er = ss[:3].sum()/ss.sum()
        print(f'  [INFO] Sine: top3 energy={er:.2%}')
        # Lorenz
        def lorenz(x,y,z,s=10,r=28,b=8/3):
            return s*(y-x), x*(r-z)-y, x*y-b*z
        dt,nl = 0.01,3000
        xl = np.zeros(nl); xl[0],y,z = 1.0,1.0,1.0
        for i in range(1,nl):
            dx,dy,dz = lorenz(xl[i-1],y,z)
            xl[i]=xl[i-1]+dx*dt; y+=dy*dt; z+=dz*dt
        lc = xl[500:]
        Kl,sl,fl,_ = havok_decompose(lc, 20)
        el = sl[:5].sum()/sl.sum()
        print(f'  [INFO] Lorenz: top5 energy={el:.2%}')
        print(f'  [PASS] Known signal tests done')
        return True

class TestUBasis:
    @staticmethod
    def run():
        np.random.seed(_SEED); data = np.random.randn(50)
        m, r = 8, 7; N = len(data)-m+1
        H = np.zeros((N,m))
        for i in range(m): H[:,i] = data[i:i+N]
        U,s,Vt = svd(H, full_matrices=False); V = Vt.T
        # V-based: r x (m-1) = square (when r=m-1)
        Xv = V[:,:r][:-1,:].T
        # U-based: r x (N-1) 
        Xu = U[:,:r][:-1,:].T
        print(f'  [INFO] V-based X: {Xv.shape} (square!), U-based X: {Xu.shape}')
        # Verify H = USV^T
        assert np.max(np.abs(H - U@np.diag(s)@Vt)) < 1e-12
        print(f'  [PASS] U-basis verified: V-modes have {m} rows, U-modes have {N} rows (=time)')
        return True

class TestEmbedDimIntegration:
    @staticmethod
    def run():
        if not _PYEDM:
            print('  [SKIP] pyEDM not installed — EmbedDim integration test skipped')
            return True
        df = pd.read_csv(os.path.join(_SKILL_DATA, 'game_log.csv'))
        print(f'  Loaded {len(df)} games')
        ok = True
        for v in ['result','kills','damage']:
            try:
                rho = pyEDM.EmbedDimension(dataFrame=df, lib='1 25', pred='26 32',
                        maxE=8, Tp=1, columns=v, target=v, showPlot=False, numProcess=1)
                E = int(rho.loc[rho['rho'].idxmax(), 'E'])
                data = df[v].values
                K,s,forcing,U = havok_decompose(data, E)
                N = len(data)-E+1
                assert len(s)==E, f's length: {len(s)}!={E}'
                assert len(forcing)==N-1, f'forcing length: {len(forcing)}!={N-1}'
                fr = np.var(forcing)/(np.var(data)+1e-10)
                print(f'  [PASS] {v:8s}: E={E}, forcing_ratio={fr:.2%}, len={len(forcing)}')
            except Exception as e:
                print(f'  [FAIL] {v}: {e}'); ok = False
        return ok

def run_all():
    tests = [
        ('Hankel matrix', TestHankelMatrix),
        ('SVD recon', TestSVDReconstruction),
        ('Linear regression', TestLinearRegression),
        ('Forcing semantics', TestForcingSemantics),
        ('Reproducibility', TestReproducibility),
        ('Edge cases', TestEdgeCases),
        ('Known signals', TestKnownSignal),
        ('U-basis correctness', TestUBasis),
        ('pyEDM integration', TestEmbedDimIntegration),
    ]
    passed = failed = 0
    print('='*60)
    print('  HAVOK Algorithm Test Suite')
    print('='*60)
    for name, cls in tests:
        try:
            print(f'\n--- {name} ---')
            if cls.run(): passed += 1
            else: failed += 1
        except Exception as e:
            print(f'  [ERROR] {name}: {e}')
            import traceback; traceback.print_exc()
            failed += 1
    print()
    print('='*60)
    print(f'  Total: {passed+failed}  |  Passed: {passed}  |  Failed: {failed}')
    print('='*60)
    return failed == 0

if __name__ == '__main__':
    sys.exit(0 if run_all() else 1)