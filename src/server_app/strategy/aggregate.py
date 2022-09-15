# Copyright 2020 Adap GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Aggregation functions for strategy implementations."""


from functools import reduce
from typing import List, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from flwr.common import NDArrays

from common.typing import NDArray
from models.metric_learning import SpreadoutRegularizer


def aggregate(results: List[Tuple[NDArrays, int]]) -> NDArrays:
    """Compute weighted average."""
    # Calculate the total number of examples used during training
    num_examples_total = sum([num_examples for _, num_examples in results])

    # Create a list of weights, each multiplied by the related number of examples
    weighted_weights = [
        [layer * num_examples for layer in weights] for weights, num_examples in results
    ]

    # Compute average weights of each layer
    weights_prime: NDArrays = [
        reduce(np.add, layer_updates) / num_examples_total
        for layer_updates in zip(*weighted_weights)
    ]
    return weights_prime


def weighted_loss_avg(results: List[Tuple[int, float]]) -> float:
    """Aggregate evaluation results obtained from multiple clients."""
    num_total_evaluation_examples = sum([num_examples for num_examples, _ in results])
    weighted_losses = [num_examples * loss for num_examples, loss in results]
    return sum(weighted_losses) / num_total_evaluation_examples


def aggregate_qffl(
    parameters: NDArrays, deltas: List[NDArrays], hs_fll: List[NDArrays]
) -> NDArrays:
    """Compute weighted average based on  Q-FFL paper."""
    demominator = np.sum(np.asarray(hs_fll))
    scaled_deltas = []
    for client_delta in deltas:
        scaled_deltas.append([layer * 1.0 / demominator for layer in client_delta])
    updates = []
    for i in range(len(deltas[0])):
        tmp = scaled_deltas[0][i]
        for j in range(1, len(deltas)):
            tmp += scaled_deltas[j][i]
        updates.append(tmp)
    new_parameters = [(u - v) * 1.0 for u, v in zip(parameters, updates)]
    return new_parameters

def aggregate_and_spreadout(results: List[Tuple[NDArrays, int]], num_clients: int, num_features: int, nu: float, lr: float) ->Tuple[NDArrays, NDArray]:
    """Compute weighted average."""
    # Create a classification matrix from class embeddings
    embeddings: NDArray = np.zeros((num_clients,num_features))
    for weights, _, cid in results:
        embeddings[cid,:] = weights[-1]
    
    embeddings = torch.nn.Parameter(torch.tensor(embeddings))
    regularizer = SpreadoutRegularizer(nu=nu)
    optimizer = torch.optim.SGD([embeddings], lr=lr)
    optimizer.zero_grad()
    loss = regularizer(embeddings, out_dims=num_clients)
    print(loss)
    loss.backward()
    optimizer.step()
    embeddings = F.normalize(embeddings).detach().cpu().numpy()
    
    # Calculate the total number of examples used during training
    num_examples_total = sum([num_examples for _, num_examples, _ in results])

    # Create a list of weights, each multiplied by the related number of examples
    feature_weights = [
        [layer * num_examples for layer in weights[:-1]] for weights, num_examples, _ in results
    ]

    # Compute average weights of each layer
    weights_prime: NDArrays = [
        reduce(np.add, layer_updates) / num_examples_total
        for layer_updates in zip(*feature_weights)
    ]
    weights_prime.append(embeddings)

    return weights_prime, embeddings