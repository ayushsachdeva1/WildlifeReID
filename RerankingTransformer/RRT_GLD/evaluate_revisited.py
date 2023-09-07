from copy import deepcopy
from functools import partial
from pprint import pprint
import os.path as osp

import sacred
import torch
import torch.nn as nn
from sacred import SETTINGS
from sacred.utils import apply_backspaces_and_linefeeds
from torch.backends import cudnn
# from visdom_logger import VisdomLogger

from models.ingredient import model_ingredient, get_model
from utils import pickle_load
from utils.data.dataset_ingredient import data_ingredient, get_loaders
# from utils.training import evaluate_time as evaluate
from utils.training import evaluate

import numpy as np

import json

ex = sacred.Experiment('RRT Evaluation', ingredients=[data_ingredient, model_ingredient])
# Filter backspaces and linefeeds
SETTINGS.CAPTURE_MODE = 'sys'
ex.captured_out_filter = apply_backspaces_and_linefeeds

# If there is a problem with pytorch version, try 
#       conda install pytorch==1.7.1 torchvision==0.8.2 torchaudio==0.7.2 cudatoolkit=11.0 -c pytorch

@ex.config
def config():
    visdom_port = None
    visdom_freq = 20
    cpu = False  # Force training on CPU
    cudnn_flag = 'benchmark'
    temp_dir = osp.join('logs', 'temp')
    resume = None
    seed = 0


@ex.automain
def main(cpu, cudnn_flag, visdom_port, visdom_freq, temp_dir, seed, resume):
    device = torch.device('cuda:0' if torch.cuda.is_available() and not cpu else 'cpu')
    print(" We are using " + str(device)  + " with device_count = " + str(torch.cuda.device_count()))
    # device = torch.device('cpu')
    # callback = VisdomLogger(port=visdom_port) if visdom_port else None
    if cudnn_flag == 'deterministic':
        setattr(cudnn, cudnn_flag, True)

    torch.manual_seed(seed)
    loaders, recall_ks = get_loaders()

    torch.manual_seed(seed)
    model = get_model()
    if resume is not None:
        checkpoint = torch.load(resume, map_location=torch.device('cpu'))
        model.load_state_dict(checkpoint['state'], strict=True)

    model.to(device)

    if torch.cuda.device_count() > 1:
        model = nn.DataParallel(model)

    model.eval()

    nn_inds_path = osp.join(loaders.query.dataset.data_dir, 'nn_inds_%s.pkl'%loaders.query.dataset.desc_name)
    cache_nn_inds = torch.from_numpy(pickle_load(nn_inds_path)).long()
    # setup partial function to simplify call
    eval_function = partial(evaluate, model=model, 
        cache_nn_inds=cache_nn_inds,
        recall=recall_ks, query_loader=loaders.query, gallery_loader=loaders.gallery, limit = None)
    
    ranks = eval_function()

    new_ranking = []

    for i in range(len(ranks)):
        elem = list(ranks[i])
        ind = elem.index(i)
        new_ranking.append(elem[:ind] + elem[ind+1:])
        
    class NpEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            return super(NpEncoder, self).default(obj)

    with open("ranks_" + temp_dir[5:] + "_top_all", 'w') as f:
        json.dump(ranks, f, cls=NpEncoder)

    return ranks

    # setup best validation logger
    metrics = eval_function()
    pprint(metrics)
    best_val = (0, metrics, deepcopy(model.state_dict()))

    return best_val[1]
