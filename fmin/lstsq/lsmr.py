"""
Code modified from scipy.sparse.linalg.lsmr

Copyright (C) 2010 David Fong and Michael Saunders
"""
import torch

from .linear_operator import aslinearoperator


# def _sym_ortho(a, b):
#     """Stable implementation of Givens rotation."""
#     if b == 0:
#         return torch.sign(a), 0, torch.abs(a)
#     elif a == 0:
#         return 0, torch.sign(b), torch.abs(b)
#     elif torch.abs(b) > torch.abs(a):
#         tau = a / b
#         s = torch.sign(b) / torch.sqrt(1 + tau * tau)
#         c = s * tau
#         r = b / s
#     else:
#         tau = b / a
#         c = torch.sign(a) / torch.sqrt(1 + tau * tau)
#         s = c * tau
#         r = a / c
#     return c, s, r


def _sym_ortho(a, b):
    """Stable implementation of Givens rotation."""
    a_sign = a.sign()
    b_sign = b.sign()
    a_abs = a.abs()
    b_abs = b.abs()

    tau = b / a
    c = a_sign / torch.sqrt(1 + tau.square())
    s = c * tau
    r = a / c

    # case 1
    case1 = b.eq(0)
    c = torch.where(case1, a_sign, c)
    s = torch.where(case1, torch.zeros_like(s), s)
    r = torch.where(case1, a_abs, r)
    stop = case1

    # case 2
    case2 = torch.logical_and(a.eq(0), ~stop)
    c = torch.where(case2, torch.zeros_like(c), c)
    s = torch.where(case2, b_sign, s)
    r = torch.where(case2, b_abs, r)
    stop.logical_or_(case2)

    # case 3
    case3 = torch.logical_and(b_abs.gt(a_abs), ~stop)
    s = torch.where(case3, b_sign / torch.sqrt(1 + 1 / tau.square()), s)
    c = torch.where(case3, s / tau, c)
    r = torch.where(case3, b / s, r)

    return c, s, r


@torch.no_grad()
def lsmr(A, b, damp=0.0, atol=1e-6, btol=1e-6, conlim=1e8,
         maxiter=None, show=False, x0=None):
    """Iterative solver for least-squares problems.

    lsmr solves the system of linear equations ``Ax = b``. If the system
    is inconsistent, it solves the least-squares problem ``min ||b - Ax||_2``.
    ``A`` is a rectangular matrix of dimension m-by-n, where all cases are
    allowed: m = n, m > n, or m < n. ``b`` is a vector of length m.
    The matrix A may be dense or sparse (usually sparse).

    Parameters
    ----------
    A : {matrix, sparse matrix, ndarray, LinearOperator}
        Matrix A in the linear system.
        Alternatively, ``A`` can be a linear operator which can
        produce ``Ax`` and ``A^H x`` using, e.g.,
        ``scipy.sparse.linalg.LinearOperator``.
    b : array_like, shape (m,)
        Vector ``b`` in the linear system.
    damp : float
        Damping factor for regularized least-squares. `lsmr` solves
        the regularized least-squares problem::
         min ||(b) - (  A   )x||
             ||(0)   (damp*I) ||_2
        where damp is a scalar.  If damp is None or 0, the system
        is solved without regularization.
    atol, btol : float, optional
        Stopping tolerances. `lsmr` continues iterations until a
        certain backward error estimate is smaller than some quantity
        depending on atol and btol.  Let ``r = b - Ax`` be the
        residual vector for the current approximate solution ``x``.
        If ``Ax = b`` seems to be consistent, ``lsmr`` terminates
        when ``norm(r) <= atol * norm(A) * norm(x) + btol * norm(b)``.
        Otherwise, lsmr terminates when ``norm(A^H r) <=
        atol * norm(A) * norm(r)``.  If both tolerances are 1.0e-6 (say),
        the final ``norm(r)`` should be accurate to about 6
        digits. (The final ``x`` will usually have fewer correct digits,
        depending on ``cond(A)`` and the size of LAMBDA.)  If `atol`
        or `btol` is None, a default value of 1.0e-6 will be used.
        Ideally, they should be estimates of the relative error in the
        entries of ``A`` and ``b`` respectively.  For example, if the entries
        of ``A`` have 7 correct digits, set ``atol = 1e-7``. This prevents
        the algorithm from doing unnecessary work beyond the
        uncertainty of the input data.
    conlim : float, optional
        `lsmr` terminates if an estimate of ``cond(A)`` exceeds
        `conlim`.  For compatible systems ``Ax = b``, conlim could be
        as large as 1.0e+12 (say).  For least-squares problems,
        `conlim` should be less than 1.0e+8. If `conlim` is None, the
        default value is 1e+8.  Maximum precision can be obtained by
        setting ``atol = btol = conlim = 0``, but the number of
        iterations may then be excessive.
    maxiter : int, optional
        `lsmr` terminates if the number of iterations reaches
        `maxiter`.  The default is ``maxiter = min(m, n)``.  For
        ill-conditioned systems, a larger value of `maxiter` may be
        needed.
    show : bool, optional
        Print iterations logs if ``show=True``.
    x0 : array_like, shape (n,), optional
        Initial guess of ``x``, if None zeros are used.
        .. versionadded:: 1.0.0

    Returns
    -------
    x : ndarray of float
        Least-square solution returned.
    itn : int
        Number of iterations used.
    normr : float
        ``norm(b-Ax)``
    normar : float
        ``norm(A^H (b - Ax))``
    norma : float
        ``norm(A)``
    conda : float
        Condition number of A.
    normx : float
        ``norm(x)``

    """
    A = aslinearoperator(A)
    b = torch.atleast_1d(b)
    if b.dim() > 1:
        b = b.squeeze()
    damp = torch.as_tensor(damp, dtype=b.dtype, device=b.device)

    msg = ('The exact solution is x = 0, or x = x0, if x0 was given   ',
           'Ax - b is small enough, given atol, btol                  ',
           'The least-squares solution is good enough, given atol     ',
           'The estimate of cond(Abar) has exceeded conlim            ',
           'Ax - b is small enough for this machine                   ',
           'The least-squares solution is good enough for this machine',
           'Cond(Abar) seems to be too large for this machine         ',
           'The iteration limit has been reached                      ')

    hdg1 = '   itn      x(1)       norm r    norm Ar'
    hdg2 = ' compatible   LS      norm A   cond A'
    pfreq = 20   # print frequency (for repeating the heading)
    pcount = 0   # print counter

    m, n = A.shape

    # stores the num of singular values
    minDim = min([m, n])

    if maxiter is None:
        maxiter = minDim

    if show:
        print(' ')
        print('LSMR            Least-squares solution of  Ax = b\n')
        print(f'The matrix A has {m} rows and {n} columns')
        print('damp = %20.14e\n' % (damp))
        print('atol = %8.2e                 conlim = %8.2e\n' % (atol, conlim))
        print('btol = %8.2e             maxiter = %8g\n' % (btol, maxiter))

    u = b
    normb = b.norm()
    if x0 is None:
        x = b.new_zeros(n)
        beta = normb.clone()
    else:
        x = torch.atleast_1d(x0)
        u = u - A.matvec(x)
        beta = u.norm()

    if beta > 0:
        u = (1 / beta) * u
        v = A.rmatvec(u)
        alpha = v.norm()
    else:
        v = b.new_zeros(n)
        alpha = b.new_tensor(0)

    if alpha > 0:
        v = (1 / alpha) * v

    # Initialize variables for 1st iteration.

    itn = b.new_tensor(0, dtype=torch.long)
    zetabar = alpha * beta
    alphabar = alpha
    rho = b.new_tensor(1)
    rhobar = b.new_tensor(1)
    cbar = b.new_tensor(1)
    sbar = b.new_tensor(0)

    h = v.clone()
    hbar = b.new_zeros(n)

    # Initialize variables for estimation of ||r||.

    betadd = beta
    betad = b.new_tensor(0)
    rhodold = b.new_tensor(1)
    tautildeold = b.new_tensor(0)
    thetatilde = b.new_tensor(0)
    zeta = b.new_tensor(0)
    d = b.new_tensor(0)

    # Initialize variables for estimation of ||A|| and cond(A)

    normA2 = alpha * alpha
    maxrbar = b.new_tensor(0)
    minrbar = b.new_tensor(0.99 * torch.finfo(b.dtype).max)
    normA = torch.sqrt(normA2)
    condA = b.new_tensor(1)
    normx = b.new_tensor(0)

    # Items for use in stopping rules, normb set earlier
    #istop = 0
    ctol = 0
    if conlim > 0:
        ctol = 1 / conlim
    normr = beta

    # Reverse the order here from the original matlab code because
    # there was an error on return when arnorm==0
    normar = alpha * beta
    if normar == 0:
        if show:
            print(msg[0])
        #return x, istop, itn, normr, normar, normA, condA, normx
        return x, itn, normr, normar, normA, condA, normx

    if show:
        print(' ')
        print(hdg1, hdg2)
        test1 = 1
        test2 = alpha / beta
        str1 = '%6g %12.5e' % (itn, x[0])
        str2 = ' %10.3e %10.3e' % (normr, normar)
        str3 = '  %8.1e %8.1e' % (test1, test2)
        print(''.join([str1, str2, str3]))

    # Main iteration loop.
    while True:
        itn = itn + 1

        # Perform the next step of the bidiagonalization to obtain the
        # next  beta, u, alpha, v.  These satisfy the relations
        #         beta*u  =  a*v   -  alpha*u,
        #        alpha*v  =  A'*u  -  beta*v.

        u *= -alpha
        u += A.matvec(v)
        beta = u.norm()

        if beta > 0:
            u *= (1 / beta)
            v *= -beta
            v += A.rmatvec(u)
            alpha = v.norm()
            if alpha > 0:
                v *= (1 / alpha)

        # At this point, beta = beta_{k+1}, alpha = alpha_{k+1}.

        # Construct rotation Qhat_{k,2k+1}.

        chat, shat, alphahat = _sym_ortho(alphabar, damp)

        # Use a plane rotation (Q_i) to turn B_i to R_i

        rhoold = rho
        c, s, rho = _sym_ortho(alphahat, beta)
        thetanew = s*alpha
        alphabar = c*alpha

        # Use a plane rotation (Qbar_i) to turn R_i^T to R_i^bar

        rhobarold = rhobar
        zetaold = zeta
        thetabar = sbar * rho
        rhotemp = cbar * rho
        cbar, sbar, rhobar = _sym_ortho(cbar * rho, thetanew)
        zeta = cbar * zetabar
        zetabar = - sbar * zetabar

        # Update h, h_hat, x.

        hbar *= - (thetabar * rho / (rhoold * rhobarold))
        hbar += h
        x += (zeta / (rho * rhobar)) * hbar
        h *= - (thetanew / rho)
        h += v

        # Estimate of ||r||.

        # Apply rotation Qhat_{k,2k+1}.
        betaacute = chat * betadd
        betacheck = -shat * betadd

        # Apply rotation Q_{k,k+1}.
        betahat = c * betaacute
        betadd = -s * betaacute

        # Apply rotation Qtilde_{k-1}.
        # betad = betad_{k-1} here.

        thetatildeold = thetatilde
        ctildeold, stildeold, rhotildeold = _sym_ortho(rhodold, thetabar)
        thetatilde = stildeold * rhobar
        rhodold = ctildeold * rhobar
        betad = - stildeold * betad + ctildeold * betahat

        # betad   = betad_k here.
        # rhodold = rhod_k  here.

        tautildeold = (zetaold - thetatildeold * tautildeold) / rhotildeold
        taud = (zeta - thetatilde * tautildeold) / rhodold
        d = d + betacheck * betacheck
        normr = torch.sqrt(d + (betad - taud)**2 + betadd * betadd)

        # Estimate ||A||.
        normA2 = normA2 + beta * beta
        normA = torch.sqrt(normA2)
        normA2 = normA2 + alpha * alpha

        # Estimate cond(A).
        maxrbar = torch.max(maxrbar, rhobarold)
        minrbar = torch.where(itn > 1, torch.min(minrbar, rhobarold), minrbar)
        # if itn > 1:
        #     minrbar = torch.min(minrbar, rhobarold)
        condA = torch.max(maxrbar, rhotemp) / torch.min(minrbar, rhotemp)

        # Test for convergence.

        # Compute norms for convergence testing.
        normar = torch.abs(zetabar)
        normx = x.norm()

        # Now use these norms to estimate certain other quantities,
        # some of which will be small near a solution.

        test1 = normr / normb
        test2 = (normar / (normA * normr)).masked_fill((normA * normr) == 0, float('inf'))
        test3 = 1 / condA
        t1 = test1 / (1 + normA * normx / normb)
        rtol = btol + atol * normA * normx / normb

        # The following tests guard against extremely small values of
        # atol, btol or ctol.  (The user may have set any or all of
        # the parameters atol, btol, conlim  to 0.)
        # The effect is equivalent to the normAl tests using
        # atol = eps,  btol = eps,  conlim = 1/eps.

        stop = ((itn >= maxiter) | (1 + test3 <= 1) | (1 + test2 <= 1) |
                (1 + t1 <= 1))

        # Allow for tolerances set by the user.

        stop = (stop | (test3 <= ctol) | (test2 <= atol) | (test1 <= rtol) |
                (itn >= maxiter))

        # See if it is time to print something.

        if show:
            if (n <= 40) or (itn <= 10) or (itn >= maxiter - 10) or \
               (itn % 10 == 0) or (test3 <= 1.1 * ctol) or \
               (test2 <= 1.1 * atol) or (test1 <= 1.1 * rtol) or \
                stop:

                if pcount >= pfreq:
                    pcount = 0
                    print(' ')
                    print(hdg1, hdg2)
                pcount = pcount + 1
                str1 = '%6g %12.5e' % (itn, x[0])
                str2 = ' %10.3e %10.3e' % (normr, normar)
                str3 = '  %8.1e %8.1e' % (test1, test2)
                str4 = ' %8.1e %8.1e' % (normA, condA)
                print(''.join([str1, str2, str3, str4]))

        if stop:
            break

    # Print the stopping condition.

    if show:
        print(' ')
        print('LSMR finished')
        #print(msg[istop])
        #print('istop =%8g    normr =%8.1e' % (istop, normr))
        print('               normr =%8.1e' % normr)
        print('    normA =%8.1e    normAr =%8.1e' % (normA, normar))
        print('itn   =%8g    condA =%8.1e' % (itn, condA))
        print('    normx =%8.1e' % (normx))
        print(str1, str2)
        print(str3, str4)

    return x, itn, normr, normar, normA, condA, normx