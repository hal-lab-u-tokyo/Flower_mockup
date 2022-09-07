import argparse
import warnings
import gc

import random
import numpy as np
import torch
from torch.utils.data import DataLoader

import flwr as fl
from flwr.server.strategy import FedAvg
from server_app.app import ServerConfig

from driver import test
from models.base_model import Net
from utils.utils_dataset import configure_dataset, load_centralized_dataset
from utils.utils_model import load_arcface_model
from common import ndarrays_to_parameters

from common import Parameters, Scalar, NDArrays
from typing import Dict, Optional, Tuple, Callable
warnings.filterwarnings("ignore")

parser = argparse.ArgumentParser("Flower Server")
parser.add_argument("--server_address", type=str, required=True, default="0.0.0.0:8080", help="server ipaddress:post")
parser.add_argument("--dataset", type=str, required=True, choices=["CIFAR10", "CelebA"], help="FL config: dataset name")
parser.add_argument("--target", type=str, required=True, help="FL config: target partitions for common dataset target attributes for celeba")
parser.add_argument("--model", type=str, required=True, choices=["tinyCNN", "GNResNet18"], help="FL config: model name")
parser.add_argument("--pretrained", type=str, required=False, choices=["IMAGENET1K_V1", None], default=None, help="pretraing recipe")
parser.add_argument("--num_rounds", type=int, required=False, default=5, help="FL config: aggregation rounds")
parser.add_argument("--num_clients", type=int, required=False, default=4, help="FL config: number of clients")
parser.add_argument("--local_epochs", type=int, required=False, default=5, help="Client fit config: local epochs")
parser.add_argument("--batch_size", type=int, required=False, default=10, help="Client fit config: batchsize")
parser.add_argument("--lr", type=float, required=False, default=0.01, help="Client fit config: learning rate")
parser.add_argument("--weight_decay", type=float, required=False, default=0.0, help="Client fit config: weigh_decay")
parser.add_argument("--criterion", type=str, required=False, default="CrossEntropy", choices=["CrossEntropy", "ArcFace"], help="Criterion of classification performance")
parser.add_argument("--scale", type=float, required=False, default=0.0, help="scale for arcface loss")
parser.add_argument("--margin", type=float, required=False, default=0.0, help="margin for arcface loss")
parser.add_argument("--save_model", type=int, required=False, default=0, help="flag for model saving")
parser.add_argument("--seed", type=int, required=False, default=1234, help="Random seed")

def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

def main():
    """Load model for
    1. server-side parameter initialization
    2. server-side parameter evaluation
    """
    # Parse command line argument `partition`
    args = parser.parse_args()
    print(args)
    set_seed(args.seed)

    dataset_config = configure_dataset(dataset_name=args.dataset, target=args.target)
    
    model: Net = load_arcface_model(name=args.model, input_spec=dataset_config["input_spec"], out_dims=dataset_config["out_dims"], pretrained=args.pretrained)
    init_parameters: Parameters = ndarrays_to_parameters(model.get_weights())

    def fit_config(server_rnd: int)-> Dict[str, Scalar]:
        config = {
            "local_epochs": args.local_epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "criterion_name": args.criterion,
            "scale": args.scale,
            "margin": args.margin
        }
        return config
    
    server_config = ServerConfig(num_rounds=args.num_rounds)
    
    def eval_config(server_rnd: int)-> Dict[str, Scalar]:
        config = {
            "val_steps": 5,
            "batch_size": args.batch_size,
        }
        return config
    
    def get_eval_fn(model: Net, dataset: str, target: str)-> Callable:
        testset = load_centralized_dataset(dataset_name=dataset, train=False, target=target)
        testloader = DataLoader(testset, batch_size=1000)
        def evaluate(server_round: int, weights: NDArrays, config: Dict[str, Scalar])-> Optional[Tuple[float, Dict[str, Scalar]]]:
            model.set_weights(weights)
            device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
            results = test(model, testloader, device=device)
            torch.cuda.empty_cache()
            gc.collect()
            return results['loss'], {"accuracy": results['acc']}
        return evaluate

    # Create strategy
    strategy = FedAvg(
        fraction_fit=1,
        fraction_evaluate=1,
        min_fit_clients=args.num_clients,
        min_evaluate_clients=args.num_clients,
        min_available_clients=args.num_clients,
        evaluate_fn=get_eval_fn(model, args.dataset, args.target),
        on_fit_config_fn=fit_config,
        on_evaluate_config_fn=eval_config,
        initial_parameters=init_parameters,
    )

    # Start Flower server for four rounds of federated learning
    fl.server.start_server(server_address=args.server_address, config=server_config, strategy=strategy)


if __name__ == "__main__":
    main()