import torch
from torch._six import nan
from torch.distributions import constraints
from torch.distributions.distribution import Distribution
from torch.distributions.utils import probs_to_logits, logits_to_probs, lazy_property, broadcast_all


class Categorical(Distribution):
    r"""
    Creates a categorical distribution parameterized by either :attr:`probs` or
    :attr:`logits` (but not both).

    .. note::
        It is equivalent to the distribution that :func:`torch.multinomial`
        samples from.

    Samples are integers from :math:`\{0, \ldots, K-1\}` where `K` is ``probs.size(-1)``.

    If :attr:`probs` is 1D with length-`K`, each element is the relative
    probability of sampling the class at that index.

    If :attr:`probs` is 2D, it is treated as a batch of relative probability
    vectors.

    .. note:: :attr:`probs` must be non-negative, finite and have a non-zero sum,
              and it will be normalized to sum to 1.

    See also: :func:`torch.multinomial`

    Example::

        >>> m = Categorical(torch.tensor([ 0.25, 0.25, 0.25, 0.25 ]))
        >>> m.sample()  # equal probability of 0, 1, 2, 3
        tensor(3)

    Args:
        probs (Tensor): event probabilities
        logits (Tensor): event log probabilities
    """
    arg_constraints = {'probs': constraints.simplex,
                       'logits': constraints.real}
    has_enumerate_support = True

    def __init__(self, probs=None, logits=None, validate_args=None):
        if (probs is None) == (logits is None):
            raise ValueError("Either `probs` or `logits` must be specified, but not both.")
        if probs is not None:
            self.probs = probs / probs.sum(-1, keepdim=True)
        else:
            self.logits = logits - logits.logsumexp(dim=-1, keepdim=True)
        self._param = self.probs if probs is not None else self.logits
        self._num_events = self._param.size()[-1]
        batch_shape = self._param.size()[:-1] if self._param.ndimension() > 1 else torch.Size()
        super(Categorical, self).__init__(batch_shape, validate_args=validate_args)

    def _new(self, *args, **kwargs):
        return self._param.new(*args, **kwargs)

    @constraints.dependent_property
    def support(self):
        return constraints.integer_interval(0, self._num_events - 1)

    @lazy_property
    def logits(self):
        return probs_to_logits(self.probs)

    @lazy_property
    def probs(self):
        return logits_to_probs(self.logits)

    @property
    def param_shape(self):
        return self._param.size()

    @property
    def mean(self):
        return self.probs.new_tensor(nan).expand(self._extended_shape())

    @property
    def variance(self):
        return self.probs.new_tensor(nan).expand(self._extended_shape())

    def sample(self, sample_shape=torch.Size()):
        sample_shape = self._extended_shape(sample_shape)
        param_shape = sample_shape + torch.Size((self._num_events,))
        probs = self.probs.expand(param_shape)
        if self.probs.dim() == 1 or self.probs.size(0) == 1:
            probs_2d = probs.view(-1, self._num_events)
        else:
            probs_2d = probs.contiguous().view(-1, self._num_events)
        sample_2d = torch.multinomial(probs_2d, 1, True)
        return sample_2d.contiguous().view(sample_shape)

    def log_prob(self, value):
        if self._validate_args:
            self._validate_sample(value)
        value = value.long().unsqueeze(-1)
        value, log_pmf = torch.broadcast_tensors(value, self.logits)
        value = value[..., :1]
        return log_pmf.gather(-1, value).squeeze(-1)

    def entropy(self):
        p_log_p = self.logits * self.probs
        return -p_log_p.sum(-1)

    def enumerate_support(self):
        num_events = self._num_events
        values = torch.arange(num_events).long()
        values = values.view((-1,) + (1,) * len(self._batch_shape))
        values = values.expand((-1,) + self._batch_shape)
        if self._param.is_cuda:
            values = values.cuda(self._param.get_device())
        return values
