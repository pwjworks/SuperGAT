from typing import Tuple, List

import torch
import torch.nn as nn
import torch.nn.functional as F
from termcolor import cprint

from torch_geometric.datasets import Planetoid
import torch_geometric.transforms as T
import torch_geometric.nn as tgnn

from attention import ExplicitGAT
from data import get_dataset_or_loader, getattr_d


def _get_attention_layer(attention_name: str):
    if attention_name == "GAT":
        return ExplicitGAT
    else:
        raise ValueError


def _to_pool_cls(pool_name):
    if pool_name in tgnn.glob.__all__ or pool_name in tgnn.pool.__all__:
        return eval("tgnn.{}".format(pool_name))
    else:
        raise ValueError("{} is not in {} or {}".format(pool_name, tgnn.glob.__all__, tgnn.pool.__all__))


def _inspect_attention_tensor(x, edge_index, att) -> bool:
    num_pos_samples = edge_index.size(1) + x.size(0)
    if att is not None and (num_pos_samples == 13264 or
                            num_pos_samples == 12431 or
                            num_pos_samples == 0):
        att_cloned = att.clone()

        if len(att.size()) == 2:
            att_cloned = torch.exp(att_cloned)
            pos_samples = att_cloned[:num_pos_samples, 0]
            neg_samples = att_cloned[num_pos_samples:, 0]
        else:
            pos_samples = att_cloned[:num_pos_samples]
            neg_samples = att_cloned[num_pos_samples:]

        print()
        pos_m, pos_s = float(pos_samples.mean()), float(pos_samples.std())
        cprint("Pos: {} +- {}".format(pos_m, pos_s), "blue")
        neg_m, neg_s = float(neg_samples.mean()), float(neg_samples.std())
        cprint("Neg: {} +- {}".format(neg_m, neg_s), "blue")
        return True
    else:
        return False


class GATNet(torch.nn.Module):

    def __init__(self, args, dataset_or_loader):
        super(GATNet, self).__init__()

        self.args = args

        attention_layer = _get_attention_layer(self.args.model_name)

        num_input_features = getattr_d(dataset_or_loader, "num_node_features")
        num_classes = getattr_d(dataset_or_loader, "num_classes")

        self.conv1 = attention_layer(
            num_input_features, args.num_hidden_features,
            heads=args.head, dropout=args.dropout, is_explicit=args.is_explicit,
            att_criterion=args.att_criterion, att_head_type=args.att_head_type,
            att_hidden_features=args.att_hidden_features,
        )

        num_input_features *= args.head
        self.conv2 = attention_layer(
            args.num_hidden_features * args.head, args.num_hidden_features,
            heads=args.head, dropout=0., is_explicit=args.is_explicit,
            att_criterion=args.att_criterion, att_head_type=args.att_head_type,
            att_hidden_features=args.att_hidden_features,
        )

        if args.pool_name is not None:
            self.pool = _to_pool_cls(args.pool_name)

        self.fc = nn.Sequential(
            nn.Linear(args.head * args.num_hidden_features, args.head * args.num_hidden_features),
            nn.ReLU(inplace=True),
            nn.Dropout(),
            nn.Linear(args.head * args.num_hidden_features, num_classes),
        )

    def forward(self, x, edge_index, batch=None) -> Tuple[torch.Tensor, None or List[torch.Tensor]]:

        x, att1 = self.conv1(x, edge_index, batch=batch)
        x = F.elu(x)

        if _inspect_attention_tensor(x, edge_index, att1):
            # print(self.conv1.att_scaling, self.conv1.att_bias)
            pass

        x, att2 = self.conv2(x, edge_index, batch=batch)
        x = F.elu(x)

        if self.args.pool_name is not None:
            x = self.pool(x, batch)

        x = self.fc(x)

        explicit_attentions = [att1, att2] if att1 is not None else None

        return x, explicit_attentions
