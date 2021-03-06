# -*- coding: utf-8 -*-

import numba as nb
import numpy as np

from . import base
from .. import errors

if hasattr(nb.core, 'dispatcher'):
    from numba.core.dispatcher import Dispatcher
else:
    from numba.core import Dispatcher


__all__ = ['One2One', 'one2one',
           'All2All', 'all2all',
           'GridFour', 'grid_four',
           'GridEight', 'grid_eight',
           'GridN',
           'FixedPostNum', 'FixedPreNum', 'FixedProb',
           'GaussianProb', 'GaussianWeight', 'DOG',
           'SmallWorld', 'ScaleFree']


class One2One(base.Connector):
    """
    Connect two neuron groups one by one. This means
    The two neuron groups should have the same size.
    """
    def __init__(self):
        super(One2One, self).__init__()

    def __call__(self, pre_indices, post_indices):
        pre_indices = np.asarray(pre_indices)
        post_indices = np.asarray(post_indices)
        self.pre_ids = np.ascontiguousarray(pre_indices.flatten(), dtype=np.int_)
        self.post_ids = np.ascontiguousarray(post_indices.flatten(), dtype=np.int_)
        try:
            assert np.size(self.pre_ids) == np.size(self.post_ids)
        except AssertionError:
            raise errors.ModelUseError(f'One2One connection must be defined in two groups with the same size, '
                                f'but we got {np.size(self.pre_ids)} != {np.size(self.post_ids)}.')
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


one2one = One2One()


class All2All(base.Connector):
    """Connect each neuron in first group to all neurons in the
    post-synaptic neuron groups. It means this kind of conn
    will create (num_pre x num_post) synapses.
    """

    def __init__(self, include_self=True):
        self.include_self = include_self
        super(All2All, self).__init__()

    def __call__(self, pre_indices, post_indices):
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()
        num_pre, num_post = len(pre_indices), len(post_indices)
        mat = np.ones((num_pre, num_post))
        if not self.include_self:
            for i in range(min([num_post, num_pre])):
                mat[i, i] = 0
        pre_ids, post_ids = np.where(mat > 0)
        self.pre_ids = np.ascontiguousarray(pre_ids, dtype=np.int_)
        self.post_ids = np.ascontiguousarray(post_ids, dtype=np.int_)
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


all2all = All2All(include_self=True)

@nb.njit
def _grid_four(height, width, row, include_self):
    conn_i = []
    conn_j = []

    for col in range(width):
        i_index = (row * width) + col
        if 0 <= row - 1 < height:
            j_index = ((row - 1) * width) + col
            conn_i.append(i_index)
            conn_j.append(j_index)
        if 0 <= row + 1 < height:
            j_index = ((row + 1) * width) + col
            conn_i.append(i_index)
            conn_j.append(j_index)
        if 0 <= col - 1 < width:
            j_index = (row * width) + col - 1
            conn_i.append(i_index)
            conn_j.append(j_index)
        if 0 <= col + 1 < width:
            j_index = (row * width) + col + 1
            conn_i.append(i_index)
            conn_j.append(j_index)
        if include_self:
            conn_i.append(i_index)
            conn_j.append(i_index)
    return conn_i, conn_j


class GridFour(base.Connector):
    """The nearest four neighbors conn method."""

    def __init__(self, include_self=False):
        super(GridFour, self).__init__()
        self.include_self = include_self

    def __call__(self, pre_indices, post_indices=None):
        if post_indices is not None:
            try:
                assert np.shape(pre_indices) == np.shape(post_indices)
            except AssertionError:
                raise errors.ModelUseError(f'The shape of pre-synaptic group should be the same with the post group. '
                                    f'But we got {np.shape(pre_indices)} != {np.shape(post_indices)}.')

        if len(pre_indices.shape) == 1:
            height, width = pre_indices.shape[0], 1
        elif len(pre_indices.shape) == 2:
            height, width = pre_indices.shape
        else:
            raise errors.ModelUseError('Currently only support two-dimensional geometry.')
        conn_i = []
        conn_j = []
        for row in range(height):
            a = _grid_four(height, width, row, include_self=self.include_self)
            conn_i.extend(a[0])
            conn_j.extend(a[1])
        conn_i = np.asarray(conn_i)
        conn_j = np.asarray(conn_j)

        pre_indices = pre_indices.flatten()
        self.pre_ids = pre_indices[conn_i]
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if post_indices is None:
            self.post_ids = pre_indices[conn_j]
        else:
            post_indices = post_indices.flatten()
            self.post_ids = post_indices[conn_j]
            if self.num_post is None:
                self.num_post = post_indices.max()


grid_four = GridFour()


@nb.njit
def _grid_n(height, width, row, n, include_self):
    conn_i = []
    conn_j = []
    for col in range(width):
        i_index = (row * width) + col
        for row_diff in range(-n, n + 1):
            for col_diff in range(-n, n + 1):
                if (not include_self) and (row_diff == col_diff == 0):
                    continue
                if 0 <= row + row_diff < height and 0 <= col + col_diff < width:
                    j_index = ((row + row_diff) * width) + col + col_diff
                    conn_i.append(i_index)
                    conn_j.append(j_index)
    return conn_i, conn_j


class GridN(base.Connector):
    """The nearest (2*N+1) * (2*N+1) neighbors conn method.

    Parameters
    ----------
    N : int
        Extend of the conn scope. For example:
        When N=1,
            [x x x]
            [x I x]
            [x x x]
        When N=2,
            [x x x x x]
            [x x x x x]
            [x x I x x]
            [x x x x x]
            [x x x x x]
    include_self : bool
        Whether create (i, i) conn ?
    """

    def __init__(self, n=1, include_self=False):
        super(GridN, self).__init__()
        self.n = n
        self.include_self = include_self

    def __call__(self, pre_indices, post_indices=None):
        if post_indices is not None:
            try:
                assert np.shape(pre_indices) == np.shape(post_indices)
            except AssertionError:
                raise errors.ModelUseError(f'The shape of pre-synaptic group should be the same with the post group. '
                                    f'But we got {np.shape(pre_indices)} != {np.shape(post_indices)}.')

        if len(pre_indices.shape) == 1:
            height, width = pre_indices.shape[0], 1
        elif len(pre_indices.shape) == 2:
            height, width = pre_indices.shape
        else:
            raise errors.ModelUseError('Currently only support two-dimensional geometry.')

        conn_i = []
        conn_j = []
        for row in range(height):
            res = _grid_n(height=height, width=width, row=row,
                          n=self.n, include_self=self.include_self)
            conn_i.extend(res[0])
            conn_j.extend(res[1])
        conn_i = np.asarray(conn_i, dtype=np.int_)
        conn_j = np.asarray(conn_j, dtype=np.int_)

        pre_indices = pre_indices.flatten()
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        self.pre_ids = pre_indices[conn_i]
        if post_indices is None:
            self.post_ids = pre_indices[conn_j]
        else:
            post_indices = post_indices.flatten()
            self.post_ids = post_indices[conn_j]
            if self.num_post is None:
                self.num_post = post_indices.max()


class GridEight(GridN):
    """The nearest eight neighbors conn method."""

    def __init__(self, include_self=False):
        super(GridEight, self).__init__(n=1, include_self=include_self)


grid_eight = GridEight()


class FixedProb(base.Connector):
    """Connect the post-synaptic neurons with fixed probability.

    Parameters
    ----------
    prob : float
        The conn probability.
    include_self : bool
        Whether create (i, i) conn ?
    seed : None, int
        Seed the random generator.
    """

    def __init__(self, prob, include_self=True, seed=None):
        super(FixedProb, self).__init__()
        self.prob = prob
        self.include_self = include_self
        self.seed = seed

    def __call__(self, pre_indices, post_indices):
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()

        num_pre, num_post = len(pre_indices), len(post_indices)
        prob_mat = np.random.random(size=(num_pre, num_post))
        if not self.include_self:
            diag_index = np.arange(min([num_pre, num_post]))
            prob_mat[diag_index, diag_index] = 1.
        conn_mat = prob_mat < self.prob
        pre_ids, post_ids = np.where(conn_mat)
        self.conn_mat = np.float_(conn_mat)
        self.pre_ids = pre_indices[pre_ids]
        self.post_ids = post_indices[post_ids]
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


class FixedPreNum(base.Connector):
    """Connect the pre-synaptic neurons with fixed number for each
    post-synaptic neuron.

    Parameters
    ----------
    num : float, int
        The conn probability (if "num" is float) or the fixed number of
        connectivity (if "num" is int).
    include_self : bool
        Whether create (i, i) conn ?
    seed : None, int
        Seed the random generator.
    """

    def __init__(self, num, include_self=True, seed=None):
        super(FixedPreNum, self).__init__()
        if isinstance(num, int):
            assert num >= 0, '"num" must be bigger than 0.'
        elif isinstance(num, float):
            assert 0. <= num <= 1., '"num" must be in [0., 1.].'
        else:
            raise ValueError(f'Unknown type: {type(num)}')
        self.num = num
        self.include_self = include_self
        self.seed = seed

    def __call__(self, pre_indices, post_indices):
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()
        num_pre, num_post = len(pre_indices), len(post_indices)
        num = self.num if isinstance(self.num, int) else int(self.num * num_pre)
        assert num <= num_pre, f'"num" must be less than "num_pre", but got {num} > {num_pre}'
        prob_mat = np.random.random(size=(num_pre, num_post))
        if not self.include_self:
            diag_index = np.arange(min([num_pre, num_post]))
            prob_mat[diag_index, diag_index] = 1.1
        arg_sort = np.argsort(prob_mat, axis=0)[:num]
        self.pre_ids = np.asarray(np.concatenate(arg_sort), dtype=np.int64)
        self.post_ids = np.asarray(np.repeat(np.arange(num_post), num_pre), dtype=np.int64)
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


class FixedPostNum(base.Connector):
    """Connect the post-synaptic neurons with fixed number for each
    pre-synaptic neuron.

    Parameters
    ----------
    num : float, int
        The conn probability (if "num" is float) or the fixed number of
        connectivity (if "num" is int).
    include_self : bool
        Whether create (i, i) conn ?
    seed : None, int
        Seed the random generator.
    """

    def __init__(self, num, include_self=True, seed=None):
        if isinstance(num, int):
            assert num >= 0, '"num" must be bigger than 0.'
        elif isinstance(num, float):
            assert 0. <= num <= 1., '"num" must be in [0., 1.].'
        else:
            raise ValueError(f'Unknown type: {type(num)}')
        self.num = num
        self.include_self = include_self
        self.seed = seed
        super(FixedPostNum, self).__init__()

    def __call__(self, pre_indices, post_indices):
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()
        num_pre = len(pre_indices)
        num_post = len(post_indices)
        num = self.num if isinstance(self.num, int) else int(self.num * num_post)
        assert num <= num_post, f'"num" must be less than "num_post", but got {num} > {num_post}'
        prob_mat = np.random.random(size=(num_pre, num_post))
        if not self.include_self:
            diag_index = np.arange(min([num_pre, num_post]))
            prob_mat[diag_index, diag_index] = 1.1
        arg_sort = np.argsort(prob_mat, axis=1)[:, num]
        self.post_ids = np.asarray(np.concatenate(arg_sort), dtype=np.int64)
        self.pre_ids = np.asarray(np.repeat(np.arange(num_pre), num_post), dtype=np.int64)
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


@nb.njit
def _gaussian_weight(pre_i, pre_width, pre_height,
                     num_post, post_width, post_height,
                     w_max, w_min, sigma, normalize, include_self):
    conn_i = []
    conn_j = []
    conn_w = []

    # get normalized coordination
    pre_coords = (pre_i // pre_width, pre_i % pre_width)
    if normalize:
        pre_coords = (pre_coords[0] / (pre_height - 1) if pre_height > 1 else 1.,
                      pre_coords[1] / (pre_width - 1) if pre_width > 1 else 1.)

    for post_i in range(num_post):
        if (pre_i == post_i) and (not include_self):
            continue

        # get normalized coordination
        post_coords = (post_i // post_width, post_i % post_width)
        if normalize:
            post_coords = (post_coords[0] / (post_height - 1) if post_height > 1 else 1.,
                           post_coords[1] / (post_width - 1) if post_width > 1 else 1.)

        # Compute Euclidean distance between two coordinates
        distance = (pre_coords[0] - post_coords[0]) ** 2
        distance += (pre_coords[1] - post_coords[1]) ** 2
        # get weight and conn
        value = w_max * np.exp(-distance / (2.0 * sigma ** 2))
        if value > w_min:
            conn_i.append(pre_i)
            conn_j.append(post_i)
            conn_w.append(value)
    return conn_i, conn_j, conn_w


class GaussianWeight(base.Connector):
    """Builds a Gaussian conn pattern between the two populations, where
    the weights decay with gaussian function.

    Specifically,

    .. math::

        w(x, y) = w_{max} \\cdot \\exp(-\\frac{(x-x_c)^2+(y-y_c)^2}{2\\sigma^2})

    where :math:`(x, y)` is the position of the pre-synaptic neuron (normalized
    to [0,1]) and :math:`(x_c,y_c)` is the position of the post-synaptic neuron
    (normalized to [0,1]), :math:`w_{max}` is the maximum weight. In order to void
    creating useless synapses, :math:`w_{min}` can be set to restrict the creation
    of synapses to the cases where the value of the weight would be superior
    to :math:`w_{min}`. Default is :math:`0.01 w_{max}`.

    Parameters
    ----------
    sigma : float
        Width of the Gaussian function.
    w_max : float
        The weight amplitude of the Gaussian function.
    w_min : float, None
        The minimum weight value below which synapses are not created (default: 0.01 * `w_max`).
    normalize : bool
        Whether normalize the coordination.
    include_self : bool
        Whether create the conn at the same position.
    """

    def __init__(self, sigma, w_max, w_min=None, normalize=True, include_self=True):
        super(GaussianWeight, self).__init__()
        self.sigma = sigma
        self.w_max = w_max
        self.w_min = w_max * 0.01 if w_min is None else w_min
        self.normalize = normalize
        self.include_self = include_self

    def __call__(self, pre_indices, post_indices):
        num_pre = np.size(pre_indices)
        num_post = np.size(post_indices)
        assert np.ndim(pre_indices) == 2
        assert np.ndim(post_indices) == 2
        pre_height, pre_width = pre_indices.shape
        post_height, post_width = post_indices.shape

        # get the connections and weights
        i, j, w = [], [], []
        for pre_i in range(num_pre):
            a = _gaussian_weight(pre_i=pre_i,
                                 pre_width=pre_width,
                                 pre_height=pre_height,
                                 num_post=num_post,
                                 post_width=post_width,
                                 post_height=post_height,
                                 w_max=self.w_max,
                                 w_min=self.w_min,
                                 sigma=self.sigma,
                                 normalize=self.normalize,
                                 include_self=self.include_self)
            i.extend(a[0])
            j.extend(a[1])
            w.extend(a[2])

        pre_ids = np.asarray(i, dtype=np.int_)
        post_ids = np.asarray(j, dtype=np.int_)
        w = np.asarray(w, dtype=np.float_)
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()
        self.pre_ids = pre_indices[pre_ids]
        self.post_ids = post_indices[post_ids]
        self.weights = w
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


@nb.njit
def _gaussian_prob(pre_i, pre_width, pre_height,
                   num_post, post_width, post_height,
                   p_min, sigma, normalize, include_self):
    conn_i = []
    conn_j = []
    conn_p = []

    # get normalized coordination
    pre_coords = (pre_i // pre_width, pre_i % pre_width)
    if normalize:
        pre_coords = (pre_coords[0] / (pre_height - 1) if pre_height > 1 else 1.,
                      pre_coords[1] / (pre_width - 1) if pre_width > 1 else 1.)

    for post_i in range(num_post):
        if (pre_i == post_i) and (not include_self):
            continue

        # get normalized coordination
        post_coords = (post_i // post_width, post_i % post_width)
        if normalize:
            post_coords = (post_coords[0] / (post_height - 1) if post_height > 1 else 1.,
                           post_coords[1] / (post_width - 1) if post_width > 1 else 1.)

        # Compute Euclidean distance between two coordinates
        distance = (pre_coords[0] - post_coords[0]) ** 2
        distance += (pre_coords[1] - post_coords[1]) ** 2
        # get weight and conn
        value = np.exp(-distance / (2.0 * sigma ** 2))
        if value > p_min:
            conn_i.append(pre_i)
            conn_j.append(post_i)
            conn_p.append(value)
    return conn_i, conn_j, conn_p


class GaussianProb(base.Connector):
    """Builds a Gaussian conn pattern between the two populations, where
    the conn probability decay according to the gaussian function.

    Specifically,

    .. math::

        p=\\exp(-\\frac{(x-x_c)^2+(y-y_c)^2}{2\\sigma^2})

    where :math:`(x, y)` is the position of the pre-synaptic neuron
    and :math:`(x_c,y_c)` is the position of the post-synaptic neuron.

    Parameters
    ----------
    sigma : float
        Width of the Gaussian function.
    normalize : bool
        Whether normalize the coordination.
    include_self : bool
        Whether create the conn at the same position.
    seed : bool
        The random seed.
    """

    def __init__(self, sigma, p_min=0., normalize=True, include_self=True, seed=None):
        super(GaussianProb, self).__init__()
        self.sigma = sigma
        self.p_min = p_min
        self.normalize = normalize
        self.include_self = include_self

    def __call__(self, pre_indices, post_indices):
        num_pre = np.size(pre_indices)
        num_post = np.size(post_indices)
        assert np.ndim(pre_indices) == 2
        assert np.ndim(post_indices) == 2
        pre_height, pre_width = pre_indices.shape
        post_height, post_width = post_indices.shape

        # get the connections
        i, j, p = [], [], []  # conn_i, conn_j, probabilities
        for pre_i in range(num_pre):
            a = _gaussian_prob(pre_i=pre_i,
                               pre_width=pre_width,
                               pre_height=pre_height,
                               num_post=num_post,
                               post_width=post_width,
                               post_height=post_height,
                               p_min=self.p_min,
                               sigma=self.sigma,
                               normalize=self.normalize,
                               include_self=self.include_self)
            i.extend(a[0])
            j.extend(a[1])
            p.extend(a[2])
        p = np.asarray(p, dtype=np.float_)
        selected_idxs = np.where(np.random.random(len(p)) < p)[0]
        i = np.asarray(i, dtype=np.int_)[selected_idxs]
        j = np.asarray(j, dtype=np.int_)[selected_idxs]
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()
        self.pre_ids = pre_indices[i]
        self.post_ids = post_indices[j]
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


@nb.njit
def _dog(pre_i, pre_width, pre_height,
         num_post, post_width, post_height,
         w_max_p, w_max_n, w_min, sigma_p, sigma_n,
         normalize, include_self):
    conn_i = []
    conn_j = []
    conn_w = []

    # get normalized coordination
    pre_coords = (pre_i // pre_width, pre_i % pre_width)
    if normalize:
        pre_coords = (pre_coords[0] / (pre_height - 1) if pre_height > 1 else 1.,
                      pre_coords[1] / (pre_width - 1) if pre_width > 1 else 1.)

    for post_i in range(num_post):
        if (pre_i == post_i) and (not include_self):
            continue

        # get normalized coordination
        post_coords = (post_i // post_width, post_i % post_width)
        if normalize:
            post_coords = (post_coords[0] / (post_height - 1) if post_height > 1 else 1.,
                           post_coords[1] / (post_width - 1) if post_width > 1 else 1.)

        # Compute Euclidean distance between two coordinates
        distance = (pre_coords[0] - post_coords[0]) ** 2
        distance += (pre_coords[1] - post_coords[1]) ** 2
        # get weight and conn
        value = w_max_p * np.exp(-distance / (2.0 * sigma_p ** 2)) - \
                w_max_n * np.exp(-distance / (2.0 * sigma_n ** 2))
        if np.abs(value) > w_min:
            conn_i.append(pre_i)
            conn_j.append(post_i)
            conn_w.append(value)
    return conn_i, conn_j, conn_w


class DOG(base.Connector):
    """Builds a Difference-Of-Gaussian (dog) conn pattern between the two populations.

    Mathematically,

    .. math::

        w(x, y) = w_{max}^+ \\cdot \\exp(-\\frac{(x-x_c)^2+(y-y_c)^2}{2\\sigma_+^2})
        -  w_{max}^- \\cdot \\exp(-\\frac{(x-x_c)^2+(y-y_c)^2}{2\\sigma_-^2})

    where weights smaller than :math:`0.01 * abs(w_{max} - w_{min})` are not created and
    self-connections are avoided by default (parameter allow_self_connections).

    Parameters
    ----------
    sigmas : tuple
        Widths of the positive and negative Gaussian functions.
    ws_max : tuple
        The weight amplitudes of the positive and negative Gaussian functions.
    w_min : float, None
        The minimum weight value below which synapses are not created
        (default: :math:`0.01 * w_{max}^+ - w_{min}^-`).
    normalize : bool
        Whether normalize the coordination.
    include_self : bool
        Whether create the conn at the same position.
    """

    def __init__(self, sigmas, ws_max, w_min=None, normalize=True, include_self=True):
        super(DOG, self).__init__()
        self.sigma_p, self.sigma_n = sigmas
        self.w_max_p, self.w_max_n = ws_max
        self.w_min = np.abs(ws_max[0] - ws_max[1]) * 0.01 if w_min is None else w_min
        self.normalize = normalize
        self.include_self = include_self

    def __call__(self, pre_indices, post_indices):
        num_pre = np.size(pre_indices)
        num_post = np.size(post_indices)
        assert np.ndim(pre_indices) == 2
        assert np.ndim(post_indices) == 2
        pre_height, pre_width = pre_indices.shape
        post_height, post_width = post_indices.shape

        # get the connections and weights
        i, j, w = [], [], []  # conn_i, conn_j, weights
        for pre_i in range(num_pre):
            a = _dog(pre_i=pre_i,
                     pre_width=pre_width,
                     pre_height=pre_height,
                     num_post=num_post,
                     post_width=post_width,
                     post_height=post_height,
                     w_max_p=self.w_max_p,
                     w_max_n=self.w_max_n,
                     w_min=self.w_min,
                     sigma_p=self.sigma_p,
                     sigma_n=self.sigma_n,
                     normalize=self.normalize,
                     include_self=self.include_self)
            i.extend(a[0])
            j.extend(a[1])
            w.extend(a[2])

        # format connections and weights
        i = np.asarray(i, dtype=np.int_)
        j = np.asarray(j, dtype=np.int_)
        w = np.asarray(w, dtype=np.float_)
        pre_indices = pre_indices.flatten()
        post_indices = post_indices.flatten()
        self.pre_ids = pre_indices[i]
        self.post_ids = post_indices[j]
        self.weights = w
        if self.num_pre is None:
            self.num_pre = pre_indices.max()
        if self.num_post is None:
            self.num_post = post_indices.max()


class ScaleFree(base.Connector):
    def __init__(self):
        raise NotImplementedError


class SmallWorld(base.Connector):
    def __init__(self):
        raise NotImplementedError
