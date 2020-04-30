import argparse
import os
from directories import *
from utils import *
import pyro
import torch
from torch import nn
import torch.nn.functional as nnf
import numpy as np
from pyro.infer import SVI, Trace_ELBO, TraceMeanField_ELBO, Predictive
import torch.optim as torchopt
from pyro import poutine
import pyro.optim as pyroopt
import torch.nn.functional as F
from utils import plot_loss_accuracy
import torch.distributions.constraints as constraints
softplus = torch.nn.Softplus()
from pyro.nn import PyroModule
from bnn import BNN
import pandas
import itertools
from lossGradients import loss_gradients, load_loss_gradients


class MoonsBNN(BNN):
    def __init__(self, hidden_size, activation, architecture, inference, 
                 epochs, lr, n_samples, warmup, n_inputs, input_shape, output_size):
        super(MoonsBNN, self).__init__("half_moons", hidden_size, activation, architecture, 
                inference, epochs, lr, n_samples, warmup, input_shape, output_size)
        self.name = self.get_name(epochs, lr, n_samples, warmup, n_inputs)


def _train_and_compute_grads(hidden_size, activation, architecture, inference, 
           epochs, lr, n_samples, warmup, n_inputs, posterior_samples):

    train_loader, _, inp_shape, out_size = \
            data_loaders(dataset_name="half_moons", batch_size=64, n_inputs=n_inputs, shuffle=True)

    bnn = MoonsBNN(hidden_size, activation, architecture, inference, 
                   epochs, lr, n_samples, warmup, n_inputs, inp_shape, out_size)
    bnn.train(train_loader=train_loader, device="cpu")

    _, test_loader, _, _ = \
        data_loaders(dataset_name="half_moons", batch_size=64, n_inputs=10000, shuffle=True)

    loss_gradients(net=bnn, n_samples=posterior_samples, savedir=bnn.name+"/", 
                    data_loader=test_loader, device="cpu", filename=bnn.name)


def parallel_grid_search(hidden_size, activation, architecture, inference, 
                         epochs, lr, n_samples, warmup, n_inputs, posterior_samples):
    from joblib import Parallel, delayed

    combinations = list(itertools.product(hidden_size, activation, architecture, inference, 
                         epochs, lr, n_samples, warmup, n_inputs, posterior_samples))
    
    Parallel(n_jobs=10)(
        delayed(_train_and_compute_grads)(*init) for init in combinations)


def build_dataset(hidden_size, activation, architecture, inference, 
          epochs, lr, n_samples, warmup, n_inputs, posterior_samples, device="cuda"):

    _, test_loader, inp_shape, out_size = \
        data_loaders(dataset_name="half_moons", batch_size=64, n_inputs=10000, shuffle=True)

    combinations = list(itertools.product(hidden_size, activation, architecture, inference, 
                      epochs, lr, n_samples, warmup, n_inputs))
    
    cols = ["hidden_size", "activation", "architecture", "inference", "epochs", "lr", 
            "n_samples", "warmup", "n_inputs", "posterior_samples"]
    df = pandas.DataFrame(columns=cols)

    for init in combinations:

        bnn = MoonsBNN(*init, inp_shape, out_size)
        bnn.load(device=device, rel_path=TESTS)
        
        for idx, p_samp in enumerate(posterior_samples):
            bnn_dict = {cols[k]:val for k, val in enumerate(init)}

            test_acc = bnn.evaluate(test_loader=test_loader, device=device, n_samples=p_samp)
            loss_grads = load_loss_gradients(n_samples=p_samp, filename=bnn.name, 
                                             savedir=bnn.name+"/", relpath=TESTS)          
            bnn_dict.update({"test_acc":test_acc, "loss_gradients":loss_grads, 
                             "posterior_samples":p_samp})

            df.loc[idx] = pandas.Series(bnn_dict)

    dataset.to_csv(TESTS+"halfMoons_lossGrads_gridSearch.csv", index = False, header=True)
    return df

def scatterplot_gridSearch_gradComponents(dataset, device="cuda", n_df_rows=100):

    sns.set()
    matplotlib.rc('font', **{'weight': 'bold', 'size': 12})
    fig, ax = plt.subplots(nrows=1, ncols=1, figsize=(10, 5), dpi=150, facecolor='w', edgecolor='k')
    sns.set_palette("cool",2)

    cols = ["loss_gradients_components","test_accuracy","posterior_samples","hidden_size"]
    components_df = pandas.DataFrame(columns=cols)

    for idx, row in dataset.head(n_df_rows).iterrows():
        loss_gradients_components = row["loss_gradients"].flatten()
        for value in loss_gradients_components:
            components_df.append({"loss_gradients_components":value,
                                  "test_accuracy":row["test_accuracy"],
                                  "posterior_samples":row["posterior_samples"],
                                  "hidden_size":row["hidden_size"]})

    g = sns.scatterplot(data=components_df, x="test_accuracy", y="loss_gradients_components", 
                        hue="posterior_samples", alpha=0.9, style="hidden_size", ax=ax)
    # g.set(xlim=(60, None))

    fig.text(0.5, 0.01, 'Test accuracy (%) ', ha='center', fontsize=12)
    fig.text(0.03, 0.5, 'Expected loss gradients components', va='center',fontsize=12,
                                                               rotation='vertical')

    ax.legend(loc='upper right', title="n. posterior samples")


def main(args):

    # === train ===

    # dataset = "half_moons"

    # init = (args.hidden_size, args.activation, args.architecture, 
    #         args.inference, args.epochs, args.lr, args.samples, args.warmup)
    
    # train_loader, test_loader, inp_shape, out_size = \
    #                         data_loaders(dataset_name=dataset, batch_size=64, 
    #                                      n_inputs=args.inputs, shuffle=True)

    # bnn = MoonsBNN(dataset, *init, inp_shape, out_size, args.inputs)
   
    # bnn.train(train_loader=train_loader, device=args.device)
    # # bnn.load(device=args.device, rel_path=DATA)

    # bnn.evaluate(test_loader=test_loader, device=args.device)

    # === grid search + plot ===

    hidden_size = [32, 128, 512]
    activation = ["leaky"]
    architecture = ["fc2"]
    inference = ["svi"]
    epochs = [5, 10, 30]
    lr = [0.01, 0.001, 0.0001]
    n_samples = [None]
    warmup = [None]
    n_inputs = [1000, 5000, 10000]
    posterior_samples = [1, 10, 50]

    init = (hidden_size, activation, architecture, inference, 
            epochs, lr, n_samples, warmup, n_inputs, posterior_samples)

    parallel_grid_search(*init)
    dataset = build_dataset(*init, device="cuda")

    dataset = pandas.read_csv(TESTS+"halfMoons_lossGrads_gridSearch.csv")
    scatterplot_gridSearch_gradComponents(dataset=dataset, device="cuda")


if __name__ == "__main__":
    assert pyro.__version__.startswith('1.3.0')
    parser = argparse.ArgumentParser(description="Toy example on half moons")

    parser.add_argument("--inputs", default=1000, type=int)
    parser.add_argument("--hidden_size", default=128, type=int, help="power of 2 >= 16")
    parser.add_argument("--activation", default="leaky", type=str, 
                        help="relu, leaky, sigm, tanh")
    parser.add_argument("--architecture", default="fc2", type=str, help="fc, fc2")
    parser.add_argument("--inference", default="svi", type=str, help="svi, hmc")
    parser.add_argument("--epochs", default=10, type=int)
    parser.add_argument("--samples", default=10, type=int)
    parser.add_argument("--warmup", default=5, type=int)
    parser.add_argument("--lr", default=0.001, type=float)
    parser.add_argument("--device", default='cpu', type=str, help="cpu, cuda")  
   
    main(args=parser.parse_args())