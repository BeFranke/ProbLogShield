from pls.workflows.ppo_dpl import main as ppo_dpl
from pls.workflows.pre_train import pre_train
from pls.workflows.evaluate import evaluate as evaluate_policy
import json
import os
from pls.observation_nets.observation_nets import Observation_net
import math


def pretrain_observation_sokoban(csv_file, img_folder, model_folder, image_dim, downsampling_size, net_class, n_train, epochs):
    net_input_size = math.ceil(image_dim / downsampling_size) ** 2
    keys = ["box(up)", "box(down)", "box(left)", "box(right)", "corner(up)", "corner(down)", "corner(left)", "corner(right)"]

    pre_train(csv_file=csv_file, root_dir=img_folder, model_folder=model_folder, n_train=n_train,
              net_class=net_class, net_input_size=net_input_size, net_output_size=8,
              image_dim=image_dim,
              downsampling_size=downsampling_size, epochs=epochs, keys=keys)

def pretrain_observation_gf(csv_file, img_folder, model_folder, image_dim, downsampling_size, net_class, n_train, epochs):
    if downsampling_size is not None:
        net_input_size = math.ceil(image_dim / downsampling_size) ** 2
    else:
        net_input_size = image_dim
    keys = ["ghost(up)", "ghost(down)", "ghost(left)", "ghost(right)"]

    pre_train(csv_file=csv_file, root_dir=img_folder, model_folder=model_folder, n_train=n_train,
              net_class=net_class, net_input_size=net_input_size, net_output_size=4,
              image_dim=image_dim,
              downsampling_size=downsampling_size, epochs=epochs, keys=keys)

def test(folder):
    cwd = os.path.join(os.path.dirname(__file__), "../..")
    path = os.path.join(cwd, folder, "config.json")
    with open(path) as json_data_file:
        config = json.load(json_data_file)
    config["model_features"]["params"]["step_limit"] = 1
    learner = config["workflow_name"]
    if "ppo" in learner:
        ppo_dpl(folder, config)


def train(folder):
    cwd = os.path.join(os.path.dirname(__file__), "../..")
    path = os.path.join(cwd, folder, "config.json")
    with open(path) as json_data_file:
        config = json.load(json_data_file)

    learner = config["workflow_name"]
    if "ppo" in learner:
        ppo_dpl(folder, config)


def evaluate(folder, model_at_step, n_test_episodes):
    path = os.path.join(folder, "config.json")
    with open(path) as json_data_file:
        config = json.load(json_data_file)

    learner = config["workflow_name"]
    if "ppo" in learner:
        return evaluate_policy(folder, model_at_step, n_test_episodes)


# def predict_states(folder):
#     path = os.path.join(folder, "config.json")
#     with open(path) as json_data_file:
#         config = json.load(json_data_file)
#     predict(folder, config)

