import gym
import torch as th
from torch import nn
import numpy as np
from typing import Union, Tuple
from torch.distributions import Categorical
import time
from stable_baselines3.common.callbacks import ConvertCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.type_aliases import (
    GymObs,
    GymStepReturn,
    Schedule,
)

from pls.deepproblog.light import DeepProbLogLayer, DeepProbLogLayer_Approx
from pls.dpl_policies.sokoban.util import get_ground_truth_of_box, get_ground_truth_of_corners, stuck
from os import path
import pickle
from gym.spaces import Box

from pls.observation_nets.observation_nets import Observation_net

WALL_COLOR = th.tensor([0], dtype=th.float32)
FLOOR_COLOR = th.tensor([1 / 6], dtype=th.float32)
BOX_TARGET_COLOR = th.tensor([2 / 6], dtype=th.float32)
BOX_ON_TARGET_COLOR = th.tensor([3 / 6], dtype=th.float32)
BOX_COLOR = th.tensor([4 / 6], dtype=th.float32)

PLAYER_COLOR = th.tensor([5 / 6], dtype=th.float32)
PLAYER_ON_TARGET_COLOR = th.tensor([1], dtype=th.float32)

PLAYER_COLORS = th.tensor(([5 / 6], [1]))
BOX_COLORS = th.tensor(([3 / 6], [4 / 6]))
OBSTABLE_COLORS = th.tensor(([0], [3 / 6], [4 / 6]))


NEIGHBORS_RELATIVE_LOCS_BOX = [
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),

]  # DO NOT CHANGE THE ORDER: up, down, left, right,
NEIGHBORS_RELATIVE_LOCS_CORNER = [
    (-2, 0),
    (2, 0),
    (0, -2),
    (0, 2),
]  # DO NOT CHANGE THE ORDER

def box_stuck_in_corner(tinygrid):
    s = stuck(
        input=tinygrid,
        box_color=BOX_COLOR,
        obsacle_colors=OBSTABLE_COLORS
    )
    return s

class Sokoban_Encoder(nn.Module):
    def __init__(self, input_size, n_actions, shielding_settings, program_path, debug_program_path, folder):
        super(Sokoban_Encoder, self).__init__()
        self.input_size = input_size
        self.n_box_locs = shielding_settings["n_box_locs"]
        self.n_corner_locs = shielding_settings["n_corner_locs"]
        self.n_actions = n_actions
        self.program_path = program_path
        self.debug_program_path = debug_program_path
        self.folder = folder
        self.shielding_settings = shielding_settings
        # self.sensor_noise = shielding_settings["sensor_noise"]
        # self.max_num_rejected_samples = shielding_settings["max_num_rejected_samples"]

    def forward(self, x):
        xx = th.flatten(x, 1)
        return xx

class Sokoban_Callback(ConvertCallback):
    def __init__(self, callback):
        super(Sokoban_Callback, self).__init__(callback)

class Sokoban_Monitor(Monitor):
    def __init__(self, *args, **kwargs):
        super(Sokoban_Monitor, self).__init__(*args, **kwargs)

    def reset(self, **kwargs) -> GymObs:
        return super(Sokoban_Monitor, self).reset(**kwargs)

    def step(self, action: Union[np.ndarray, int]) -> GymStepReturn:
        if self.needs_reset:
            raise RuntimeError("Tried to step environment that needs reset")
        observation, reward, done, info = self.env.step(action)
        self.rewards.append(reward)

        if done:
            self.needs_reset = True
            ep_rew = sum(self.rewards)
            ep_len = len(self.rewards)

            ep_info = {
                "r": round(ep_rew, 6),
                "l": ep_len,
                "t": round(time.time() - self.t_start, 6),
                "last_r": reward,
                # "violate_constraint": violate_constraint,
                "is_success": info["all_boxes_on_target"]
                # "abs_safety_shielded": ep_abs_safety_shielded,
                # "abs_safety_base": ep_abs_safety_base
            }
            for key in self.info_keywords:
                ep_info[key] = info[key]
            self.episode_returns.append(ep_rew)
            self.episode_lengths.append(ep_len)
            self.episode_times.append(time.time() - self.t_start)
            ep_info.update(self.current_reset_info)
            if self.results_writer:
                self.results_writer.write_row(ep_info)
            info["episode"] = ep_info
            # info["is_success"] = True  # Idk what this should be
        self.total_steps += 1
        return observation, reward, done, info




class Sokoban_DPLActorCriticPolicy(ActorCriticPolicy):
    def __init__(
        self,
        observation_space: gym.spaces.Space,
        action_space: gym.spaces.Space,
        lr_schedule: Schedule,
        image_encoder: Sokoban_Encoder = None,
        alpha=0.5,
        differentiable_shield = True,
        input_size=1,
        **kwargs
    ):
        observation_space = Box(
            low=-1,
            high=1,
            shape=(
                input_size, input_size
            )
        )
        super(Sokoban_DPLActorCriticPolicy, self).__init__(observation_space,action_space, lr_schedule, **kwargs)
        ###############################

        self.image_encoder = image_encoder
        self.input_size = self.image_encoder.input_size

        self.n_box_locs = self.image_encoder.n_box_locs
        self.n_corner_locs = self.image_encoder.n_corner_locs

        self.n_actions = self.image_encoder.n_actions
        self.program_path = self.image_encoder.program_path
        self.debug_program_path = self.image_encoder.debug_program_path
        self.folder = self.image_encoder.folder
        self.sensor_noise = self.image_encoder.shielding_settings["sensor_noise"]
        self.max_num_rejected_samples = self.image_encoder.shielding_settings["max_num_rejected_samples"]
        self.use_learned_observations = self.image_encoder.shielding_settings["use_learned_observations"]
        self.noisy_observations = self.image_encoder.shielding_settings["noisy_observations"]
        self.observation_type = self.image_encoder.shielding_settings["observation_type"]
        self.alpha = alpha
        self.differentiable_shield = differentiable_shield


        # TODO to load the model
        self.program_path = path.join('/Users/wenchi/PycharmProjects/pls/pls/workflows/../../experiments_trials3/sokoban/2box5map_gray/PLS_perfect/seed1/../../../data/sokoban_corner2.pl')
        self.debug_program_path = path.join('/Users/wenchi/PycharmProjects/pls/pls/workflows/../../experiments_trials3/sokoban/2box5map_gray/PLS_perfect/seed1/../../../data/sokoban_corner2.pl')
        with open(self.program_path) as f:
            self.program = f.read()
        with open(self.debug_program_path) as f:
            self.debug_program = f.read()

        ##### SOFT SHILDENG WITH GROUND TRUTH ####
        # IMPORTANT: THE ORDER OF QUERIES IS THE ORDER OF THE OUTPUT
        self.queries = [
           "safe_action(no_op)",
           "safe_action(push_up)",
           "safe_action(push_down)",
           "safe_action(push_left)",
           "safe_action(push_right)",
           "safe_action(move_up)",
           "safe_action(move_down)",
           "safe_action(move_left)",
           "safe_action(move_right)"
       ][: self.n_actions]

        # if self.detect_boxes:
        #     self.box_layer = nn.Sequential(
        #         nn.Linear(self.input_size, 128),
        #         nn.ReLU(),
        #         nn.Linear(128, self.n_box_locs),
        #         nn.Sigmoid(),  # TODO : add a flag
        #     )
        #
        # if self.detect_corners:
        #     self.corner_layer = nn.Sequential(
        #         nn.Linear(self.input_size, 128),
        #         nn.ReLU(),
        #         nn.Linear(128, self.n_corner_locs),
        #         nn.Sigmoid(),
        #     )

        if self.alpha == 0:
            # NO shielding
            pass
        else:
            # HARD shielding and SOFT shielding
            input_struct = {
                "box": [i for i in range(self.n_box_locs)],
                "corner": [i for i in range(self.n_box_locs,
                                            self.n_box_locs + self.n_corner_locs)],
                "action": [i for i in range(self.n_box_locs + self.n_corner_locs,
                                            self.n_box_locs + self.n_corner_locs + self.n_actions)],
            }
            query_struct = {
                "safe_action": {
                    "no_op": 0,
                    "push_up": 1,
                    "push_down": 2,
                    "push_left": 3,
                    "push_right": 4
                }}

            # action_lst = ['no_op', 'push_up', 'push_down', 'push_left', 'push_right', 'move_up', 'move_down',
            #               'move_left', 'move_right']
            # query_struct = {"safe_action": dict(zip(action_lst[:self.n_actions], range(self.n_actions)))}
            cache_path = path.join(self.folder, "../../../data", "dpl_layer.p")
            # cache_path = path.join("/Users/wenchi/PycharmProjects/pls/experiments_trials3/sokoban/2box5map_gray/data", "dpl_layer.p")
            self.dpl_layer = self.get_layer(
                cache_path,
                program=self.debug_program, queries=self.queries, evidences=["safe_next"],
                input_struct=input_struct, query_struct=query_struct
            )
            if self.use_learned_observations:
                observation_model_path = path.join(self.folder, "../../data", self.observation_type)
                observation_model_path = path.join("/Users/wenchi/PycharmProjects/pls/experiments_trials3/sokoban/2box5map_gray/data/observation_model_10000_examples.pt")
                use_cuda = False
                device = th.device("cuda" if use_cuda else "cpu")
                self.observation_model = Observation_net(input_size=self.input_size*self.input_size, output_size=8).to(device)
                self.observation_model.load_state_dict(th.load(observation_model_path))

        if self.alpha == "learned":
            self.alpha_net = nn.Sequential(
                    nn.Linear(self.input_size, 128),
                    nn.ReLU(),
                    nn.Linear(128, 1),
                    nn.Sigmoid(),
                )


        debug_queries = ["safe_next"]
        debug_query_struct = {"safe_next": 0}
        debug_input_struct = {
            "box": [i for i in range(self.n_box_locs)],
            "corner": [i for i in range(self.n_box_locs,
                                        self.n_box_locs + self.n_corner_locs)],
            "action": [i for i in range(self.n_box_locs + self.n_corner_locs,
                                        self.n_box_locs + self.n_corner_locs + self.n_actions)]
        }
        cache_path = path.join(self.folder, "../../../data", "query_safety_layer.p")
        # cache_path = path.join("/Users/wenchi/PycharmProjects/pls/experiments_trials3/sokoban/2box5map_gray/data", "query_safety_layer.p")

        self.query_safety_layer = self.get_layer(
            cache_path,
            program=self.debug_program,
            queries=debug_queries,
            evidences=[],
            input_struct=debug_input_struct,
            query_struct=debug_query_struct
        )
        self._build(lr_schedule)

    def get_layer(self, cache_path, program, queries, evidences, input_struct, query_struct):
        if path.exists(cache_path):
            return pickle.load(open(cache_path, "rb"))

        layer = DeepProbLogLayer_Approx(
            program=program, queries=queries, evidences=evidences,
            input_struct=input_struct, query_struct=query_struct
        )
        pickle.dump(layer, open(cache_path, "wb"))
        return layer

    def logging_per_episode(self, mass, object_detect_probs, base_policy, action_lookup):
        abs_safe_next_shielded = self.get_step_safety(
            mass.probs,
            object_detect_probs["ground_truth_box"],
            object_detect_probs["ground_truth_corner"],
        )
        abs_safe_next_base = self.get_step_safety(
            base_policy,
            object_detect_probs["ground_truth_box"],
            object_detect_probs["ground_truth_corner"],
        )
        rel_safe_next_shielded = self.get_step_safety(
            mass.probs,
            object_detect_probs["box"],
            object_detect_probs["corner"],
        )
        rel_safe_next_base = self.get_step_safety(
            base_policy,
            object_detect_probs["box"],
            object_detect_probs["corner"],
        )
        return abs_safe_next_shielded, abs_safe_next_base, rel_safe_next_shielded, rel_safe_next_base
    def logging_per_step(self, mass, object_detect_probs, base_policy, action_lookup, logger):
        for act in range(self.action_space.n):
            logger.record(
                f"policy/shielded {action_lookup[act]}",
                float(mass.probs[0][act]),
            )
        if object_detect_probs.get("alpha") is not None:
            logger.record(
                f"safety/alpha",
                float(object_detect_probs.get("alpha")),
            )

    def get_step_safety(self, policy_distribution, box_probs, corner_probs):
        with th.no_grad():
            abs_safe_next = self.query_safety_layer(
                x={
                    "box": box_probs,
                    "corner": corner_probs,
                    "action": policy_distribution,
                }
            )
            return abs_safe_next["safe_next"]

    def forward(self, x, tinygrid, deterministic: bool = False):
        """
        Forward pass in all the networks (actor and critic)

        :param obs: Observation
        :param deterministic: Whether to sample or use deterministic actions
        :return: action, value and log probability of the action
        """
        # Preprocess the observation if needed
        obs = self.image_encoder(x)
        features = self.extract_features(obs)
        latent_pi, latent_vf = self.mlp_extractor(features)
        # Evaluate the values for the given observations
        values = self.value_net(latent_vf)
        distribution = self._get_action_dist_from_latent(latent_pi)
        base_actions = distribution.distribution.probs

        with th.no_grad():
            if tinygrid is None:
                ground_truth_box, ground_truth_corner = None, None
            else:
                ground_truth_box = get_ground_truth_of_box(
                    input=tinygrid, agent_colors=PLAYER_COLORS, box_colors=BOX_COLORS,
                )
                ground_truth_corner = get_ground_truth_of_corners(
                    input=tinygrid, agent_colors=PLAYER_COLORS, obsacle_colors=OBSTABLE_COLORS, floor_color=FLOOR_COLOR,
                )
        if self.use_learned_observations:
            output = self.observation_model(x)
            if self.noisy_observations:
                boxes_and_corners = self.observation_model.sigmoid(output)
                boxes = boxes_and_corners[:, :self.n_box_locs]
                corners = boxes_and_corners[:, self.n_box_locs:]
            else:
                boxes_and_corners = (self.observation_model.sigmoid(output) > 0.5).float()
                boxes = boxes_and_corners[:, :self.n_box_locs]
                corners = boxes_and_corners[:, self.n_box_locs:]
        else:
            boxes = ground_truth_box
            corners = ground_truth_corner

        object_detect_probs = {
            "ground_truth_box": ground_truth_box,
            "ground_truth_corner": ground_truth_corner,
            "box": boxes,
            "corner": corners
        }

        if self.alpha == 0:
            actions = distribution.get_actions(deterministic=deterministic)
            log_prob = distribution.log_prob(actions)
            object_detect_probs["alpha"] = 0
            return (actions, values, log_prob, distribution.distribution, [object_detect_probs, base_actions])

        if not self.differentiable_shield and self.alpha == 1: # VSRL
            num_rejected_samples = 0
            while True:
                actions = distribution.get_actions(deterministic=deterministic)
                # check if the action is safe
                with th.no_grad():
                    vsrl_actions_encoding = th.eye(self.n_actions)[actions][:, 1:]
                    unsafe_actions = th.logical_and(boxes, corners)
                    actions_are_unsafe = th.logical_and(vsrl_actions_encoding, unsafe_actions)
                    # # Using problog to model check
                    # results = self.query_safety_layer(
                    #     x={
                    #         "box": boxes,
                    #         "corner": corners,
                    #         "action": th.eye(self.n_actions)[actions],
                    #     }
                    # )
                    # safe_next = results["safe_next"]
                    if not th.any(actions_are_unsafe) or num_rejected_samples > self.max_num_rejected_samples:
                        break
                    else: # sample another action
                        num_rejected_samples += 1
            log_prob = distribution.log_prob(actions)
            object_detect_probs["num_rejected_samples"] = num_rejected_samples
            object_detect_probs["alpha"] = 1
            return (actions, values, log_prob, distribution.distribution, [object_detect_probs, base_actions])

        if self.differentiable_shield:
            results = self.dpl_layer(
                x={
                    "box": boxes,
                    "corner": corners,
                    "action": base_actions,
                }
            )
            if self.alpha == "learned":
                alpha = self.alpha_net(obs)
                object_detect_probs["alpha"] = alpha
            else:
                alpha = self.alpha
        else:
            with th.no_grad():
                results = self.dpl_layer(
                    x={
                        "box": boxes,
                        "corner": corners,
                        "action": base_actions,
                    }
                )

            if self.alpha == "learned":
                raise NotImplemented
            else:
                alpha = self.alpha

        object_detect_probs["alpha"] = alpha
        safeast_actions = results["safe_action"]
        actions = alpha * safeast_actions + (1 - alpha) * base_actions


        mass = Categorical(probs=actions)
        if not deterministic:
            actions = mass.sample()
        else:
            actions = th.argmax(mass.probs,dim=1)
        log_prob = mass.log_prob(actions)



        return (actions, values, log_prob, mass, [object_detect_probs, base_actions])


    # def no_shielding(self, distribution, values, x, deterministic):
    #     actions = distribution.get_actions(deterministic=deterministic)
    #     log_prob = distribution.log_prob(actions)
    #     with th.no_grad():
    #         ground_truth_box = get_ground_truth_of_box(
    #             input=x,
    #             agent_colors=PLAYER_COLORS,
    #             box_colors=BOX_COLORS,
    #         )
    #         ground_truth_corner = get_ground_truth_of_corners(
    #             input=x,
    #             agent_colors=PLAYER_COLORS,
    #             obsacle_colors=OBSTABLE_COLORS,
    #             floor_color=FLOOR_COLOR,
    #         )
    #
    #         base_actions = distribution.distribution.probs
    #
    #         object_detect_probs = {
    #             "ground_truth_box": ground_truth_box,
    #             "ground_truth_corner": ground_truth_corner,
    #         }
    #
    #     return (
    #         actions,
    #         values,
    #         log_prob,
    #         distribution.distribution,
    #         [object_detect_probs, base_actions],
    #     )

    def evaluate_actions(
        self, obs: th.Tensor, tinygrid: th.Tensor, actions: th.Tensor
    ) -> Tuple[th.Tensor, th.Tensor, th.Tensor]:
        """
        Evaluate actions according to the current policy,
        given the observations.

        :param obs:
        :param actions:
        :return: estimated value, log likelihood of taking those actions
            and entropy of the action distribution.
        """
        if not self.differentiable_shield and self.alpha == 1:
            obs = self.image_encoder(obs)
            features = self.extract_features(obs)
            latent_pi, latent_vf = self.mlp_extractor(features)
            distribution = self._get_action_dist_from_latent(latent_pi)
            log_prob = distribution.log_prob(actions)
            values = self.value_net(latent_vf)
            return values, log_prob, distribution.entropy()

        _, values, _, mass, _ = self.forward(obs, tinygrid=tinygrid)
        log_prob = mass.log_prob(actions)
        return values, log_prob, mass.entropy()

    def _predict(self, observation: th.Tensor, deterministic: bool = False, tinygrid = None) -> th.Tensor:
        with th.no_grad():
            # tinygrid = None # this is actually not used
            _actions, values, log_prob, mass, _  = self.forward(observation, tinygrid, deterministic)
            return _actions


