import torch
from collections import OrderedDict, MutableMapping


def to_tensor(value, dtype=torch.float32):
    if value is None:
        return None
    if torch.is_tensor(value):
        return value.detach().to(dtype)
    return torch.tensor(value, dtype=dtype)


class Metric:
    def __init__(self, is_distributed=False):
        self.is_distributed = is_distributed
        self.reset_states()

    def __call__(self, *args, full_stats=False, **kwargs):
        if len(args) > 0:
            return self.update_state(*args, **kwargs)
        else:
            return self.report(full_stats=full_stats)

    def __format__(self, *args, **kwargs):
        return format(self(), *args, **kwargs)


class Mean(Metric):
    def reset_states(self):
        self.cumsum = 0.0
        self.samples = 0.0

    def update_state(self, value, weight=None):
        value = to_tensor(value, dtype=torch.float32)
        weight = to_tensor(weight, dtype=torch.float32)
        if weight is None and hasattr(value, 'shape'):
            weight = torch.prod(to_tensor(value.shape))
            value = value.sum()
        if weight is None:
            weight = to_tensor(1.0, dtype=torch.float32)

        self.samples += weight.cpu().item()
        self.cumsum += value.cpu().item()

    def report(self, full_stats=False):
        if full_stats:
            return self.cumsum, self.samples
        if self.samples == 0:
            return 0
        return self.cumsum / self.samples


class AccumulatedMetric(Metric):
    def __init__(self, accumulate_fn=None, **kwargs):
        if not hasattr(self, '_accumulate'):
            self._accumulate = accumulate_fn
        super().__init__(**kwargs)

    def reset_states(self):
        self.value = 0.0

    def update_state(self, value):
        self.value = self._accumulate(self.value, to_tensor(value).cpu().item())

    def report(self, full_stats=False):
        return self.value


class LastValue(AccumulatedMetric):
    def _accumulate(self, acc, value):
        return value


class MetricsContext(MutableMapping):
    def __init__(self, **kwargs):
        super().__init__()
        self.metrics = OrderedDict(**kwargs)

    def log(self, name, *args, **kwargs):
        self[name](*args, **kwargs)

    def collect(self, is_distributed=False, full_stats=False):
        vals = {k: val(full_stats=full_stats) for k, val in self.metrics.items()}
        distributed_vals = []
        distributed_keys = []
        distributed_lens = []
        for name, m in self.metrics.items():
            if m.is_distributed:
                if isinstance(vals[name], tuple):
                    distributed_vals.extend(vals[name])
                    distributed_lens.append(len(vals[name]))
                else:
                    distributed_lens.append(1)
                distributed_keys.append(name)
            m.reset_states()
        if is_distributed:
            values = torch.tensor(distributed_vals, dtype=torch.float32).cuda()
            torch.distributed.all_reduce(values)
            values /= torch.distributed.get_world_size()
            values = list(values.cpu())
            offset = 0
            for k, clen in zip(distributed_keys, distributed_lens):
                if clen == 1:
                    vals[k] = values[offset]
                else:
                    vals[k] = tuple(values[offset:offset + clen])
                offset += clen
        return vals

    def __len__(self):
        return len(self.metrics)

    def __iter__(self):
        return iter(self.metrics)

    def __getitem__(self, idx):
        if idx not in self.metrics:
            self.metrics[idx] = Mean()
        return self.metrics[idx]

    def __delitem__(self, name):
        del self.metrics[name]

    def __setitem__(self, name, value):
        self.metrics[name] = value
