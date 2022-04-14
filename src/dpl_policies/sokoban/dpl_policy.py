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

from deepproblog.light import DeepProbLogLayer, DeepProbLogLayer_Approx
from dpl_policies.sokoban.util import get_ground_truth_of_box, get_ground_truth_of_corners, stuck
from os import path
import pickle

WALL_COLOR = th.tensor([0] * 3, dtype=th.float32)
FLOOR_COLOR = th.tensor([1 / 6] * 3, dtype=th.float32)
BOX_TARGET_COLOR = th.tensor([2 / 6] * 3, dtype=th.float32)
BOX_ON_TARGET_COLOR = th.tensor([3 / 6] * 3, dtype=th.float32)
BOX_COLOR = th.tensor([4 / 6] * 3, dtype=th.float32)

PLAYER_COLOR = th.tensor([5 / 6] * 3, dtype=th.float32)
PLAYER_ON_TARGET_COLOR = th.tensor([1] * 3, dtype=th.float32)

PLAYER_COLORS = th.tensor(([5 / 6] * 3, [1] * 3))
BOX_COLORS = th.tensor(([3 / 6] * 3, [4 / 6] * 3))
OBSTABLE_COLORS = th.tensor(([0] * 3, [3 / 6] * 3, [4 / 6] * 3))


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
            violate_constraint = stuck(
                input=th.from_numpy(observation)[None,:,:,:],
                box_colors=BOX_COLOR,
                obsacle_colors=OBSTABLE_COLORS
            )
            # if violate_constraint:
            #     print("dd")
            ep_info = {
                "r": round(ep_rew, 6),
                "l": ep_len,
                "t": round(time.time() - self.t_start, 6),
                "last_r": reward,
                "violate_constraint": violate_constraint,
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

# class Sokoban_DPLDQNPolicy(DQNPolicy):
#     def __init__(self,
#                  observation_space: gym.spaces.Space,
#                  action_space: gym.spaces.Space,
#                  lr_schedule: Schedule,
#                  image_encoder: Sokoban_Encoder = None,
#                  **kwargs):
#
#         super(Sokoban_DPLDQNPolicy, self).__init__(observation_space,action_space, lr_schedule, **kwargs)
#         ###############################
#         self.image_encoder = image_encoder
#         self.input_size = self.image_encoder.input_size
#         self.shield = self.image_encoder.shield
#
#         self.detect_boxes = self.image_encoder.detect_boxes
#         self.detect_corners = self.image_encoder.detect_corners
#
#         self.n_box_locs = self.image_encoder.n_box_locs
#         self.n_corner_locs = self.image_encoder.n_corner_locs
#
#         self.n_actions = self.image_encoder.n_actions
#         self.program_path = self.image_encoder.program_path
#         with open(self.program_path) as f:
#             self.program = f.read()
#         if self.detect_boxes:
#             self.box_layer = nn.Sequential(
#                 nn.Linear(self.input_size, 128),
#                 nn.ReLU(),
#                 nn.Linear(128, self.n_box_locs),
#                 nn.Sigmoid(),  # TODO : add a flag
#             )
#
#         if self.detect_corners:
#             self.corner_layer = nn.Sequential(
#                 nn.Linear(self.input_size, 128),
#                 nn.ReLU(),
#                 nn.Linear(128, self.n_corner_locs),
#                 nn.Sigmoid(),
#             )
#
#         if self.shield:
#             self.evidences = ["safe_next"]
#             # IMPORTANT: THE ORDER OF QUERIES IS THE ORDER OF THE OUTPUT
#             self.queries = [
#                                "safe_action(no_op)",
#                                "safe_action(push_up)",
#                                "safe_action(push_down)",
#                                "safe_action(push_left)",
#                                "safe_action(push_right)",
#                                "safe_action(move_up)",
#                                "safe_action(move_down)",
#                                "safe_action(move_left)",
#                                "safe_action(move_right)",
#                            ][: self.n_actions]
#             self.queries += [
#                 "box(0, 1)",
#                 "box(-1, 0)",
#                 "box(1, 0)",
#                 "box(0, -1)",
#                 "corner(0, 2)",
#                 "corner(-2, 0)",
#                 "corner(2, 0)",
#                 "corner(0, -2)",
#             ]
#             self.dpl_layer = DeepProbLogLayer(
#                 program=self.program, queries=self.queries, evidences=self.evidences
#             )
#
#         debug_queries = ["safe_next"]
#         self.query_safety_layer = DeepProbLogLayer(
#             program=self.program, queries=debug_queries
#         )
#         self._build(lr_schedule)
#
#     def logging(self, mass, object_detect_probs, base_policy, action_lookup, logger):
#         for act in range(self.action_space.n):
#             logger.record(
#                 f"policy/shielded {action_lookup[act]}",
#                 float(mass.probs[0][act]),
#             )
#         for direction in [0, 1, 2, 3]:  # TODO: order matters: use a map
#             if "prob_box_prior" in object_detect_probs:
#                 logger.record(
#                     f"prob/prob_box_prior_{direction}",
#                     float(object_detect_probs["prob_box_prior"][0][direction]),
#                 )
#             if "prob_corner_prior" in object_detect_probs:
#                 logger.record(
#                     f"prob/prob_corner_prior_{direction}",
#                     float(object_detect_probs["prob_corner_prior"][0][direction]),
#                 )
#             if "prob_box_posterior" in object_detect_probs:
#                 logger.record(
#                     f"prob/prob_box_posterior_{direction}",
#                     float(object_detect_probs["prob_box_posterior"][0][direction]),
#                 )
#                 error_box_posterior = (
#                     object_detect_probs["ground_truth_box"]
#                     - object_detect_probs["prob_box_posterior"]
#                 ).abs()
#                 logger.record(
#                     f"error/error_box_posterior_{direction}",
#                     float(error_box_posterior[0][direction]),
#                 )
#             if "prob_corner_posterior" in object_detect_probs:
#                 logger.record(
#                     f"prob/prob_corner_posterior_{direction}",
#                     float(object_detect_probs["prob_corner_posterior"][0][direction]),
#                 )
#                 error_corner_posterior = (
#                     object_detect_probs["ground_truth_corner"]
#                     - object_detect_probs["prob_corner_posterior"]
#                 ).abs()
#                 logger.record(
#                     f"error/error_corner_posterior_{direction}",
#                     float(error_corner_posterior[0][direction]),
#                 )
#
#     def get_step_safety(self, policy_distribution, box_probs, corner_probs):
#         with th.no_grad():
#             abs_safe_next = self.query_safety_layer(
#                 x={
#                     "box": box_probs,
#                     "corner": corner_probs,
#                     "action": policy_distribution,
#                 }
#             )
#             return abs_safe_next["safe_next"]
#
#     def evaluate_safety_shielded(self, obs: th.Tensor):
#         with th.no_grad():
#             _, _, _, mass, (object_detect_probs, base_policy) = self.forward(obs)
#             return self.get_step_safety(
#                 mass.probs,
#                 object_detect_probs["ground_truth_box"],
#                 object_detect_probs["ground_truth_corner"],
#             )
#
#     def _sample_action(
#         self, learning_starts: int, action_noise: Optional[ActionNoise] = None
#     ) -> Tuple[np.ndarray, np.ndarray]:
#         """
#         Sample an action according to the exploration policy.
#         This is either done by sampling the probability distribution of the policy,
#         or sampling a random action (from a uniform distribution over the action space)
#         or by adding noise to the deterministic output.
#
#         :param action_noise: Action noise that will be used for exploration
#             Required for deterministic policy (e.g. TD3). This can also be used
#             in addition to the stochastic policy for SAC.
#         :param learning_starts: Number of steps before learning for the warm-up phase.
#         :return: action to take in the environment
#             and scaled action that will be stored in the replay buffer.
#             The two differs when the action space is not normalized (bounds are not [-1, 1]).
#         """
#         # Select action randomly or according to policy
#         if self.num_timesteps < learning_starts and not (self.use_sde and self.use_sde_at_warmup):
#             # Warmup phase
#             unscaled_action = np.array([self.action_space.sample()])
#         else:
#             # Note: when using continuous actions,
#             # we assume that the policy uses tanh to scale the action
#             # We use non-deterministic action in the case of SAC, for TD3, it does not matter
#             unscaled_action, _ = self.predict(self._last_obs, deterministic=False)
#
#         # Rescale the action from [low, high] to [-1, 1]
#         if isinstance(self.action_space, gym.spaces.Box):
#             scaled_action = self.policy.scale_action(unscaled_action)
#
#             # Add noise to the action (improve exploration)
#             if action_noise is not None:
#                 scaled_action = np.clip(scaled_action + action_noise(), -1, 1)
#
#             # We store the scaled action in the buffer
#             buffer_action = scaled_action
#             action = self.policy.unscale_action(scaled_action)
#         else:
#             # Discrete case, no need to normalize or clip
#             buffer_action = unscaled_action
#             action = buffer_action
#         return action, buffer_action


class Sokoban_DPLActorCriticPolicy(ActorCriticPolicy):
    def __init__(
        self,
        observation_space: gym.spaces.Space,
        action_space: gym.spaces.Space,
        lr_schedule: Schedule,
        image_encoder: Sokoban_Encoder = None,
        alpha=0.5,
        differentiable_shield = True,
        **kwargs
    ):
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
        self.alpha = alpha
        self.differentiable_shield = differentiable_shield

        with open(self.program_path) as f:
            self.program = f.read()
        with open(self.debug_program_path) as f:
            self.debug_program = f.read()

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


        self.evidences = ["safe_next"]
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

        # if "sokoban_corner2_.pl" in self.program_path:
        #     # SOFT shielding
        #     input_struct = {
        #         "box": [i for i in range(self.n_box_locs)],
        #         "corner": [i for i in range(self.n_box_locs,
        #                                     self.n_box_locs + self.n_corner_locs)],
        #         "action": [i for i in range(self.n_box_locs + self.n_corner_locs,
        #                                     self.n_box_locs + self.n_corner_locs + self.n_actions)],
        #     }
        #     query_struct = {"safe_action": [i for i in range(self.n_actions)]}
        #     cache_path = path.join(self.folder, "dpl_layer.p")
        #     self.dpl_layer = self.get_layer(
        #         cache_path,
        #         program=self.program, queries=self.queries, evidences=[],
        #         input_struct=input_struct, query_struct=query_struct
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
            query_struct = {"safe_action": [i for i in range(self.n_actions)]}

            cache_path = path.join(self.folder, "dpl_layer.p")
            self.dpl_layer = self.get_layer(
                cache_path,
                program=self.program, queries=self.queries, evidences=["safe_next"],
                input_struct=input_struct, query_struct=query_struct
            )

        if self.alpha == "learned":
            self.alpha_net = nn.Sequential(
                    nn.Linear(self.input_size, 128),
                    nn.ReLU(),
                    nn.Linear(128, 1),
                    nn.Sigmoid(),
                )

        # For all settings, calculate "safe_next"
        debug_queries = ["safe_next"]
        debug_query_struct = {"safe_next": [i for i in range(1)]}
        debug_input_struct = {
            "box": [i for i in range(self.n_box_locs)],
            "corner": [i for i in range(self.n_box_locs,
                                        self.n_box_locs + self.n_corner_locs)],
            "action": [i for i in range(self.n_box_locs + self.n_corner_locs,
                                        self.n_box_locs + self.n_corner_locs + self.n_actions)]
        }
        cache_path = path.join(self.folder, "query_safety_layer.p")
        self.query_safety_layer = self.get_layer(
            cache_path,
            program=self.program,
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
        return abs_safe_next_shielded, abs_safe_next_base
    def logging_per_step(self, mass, object_detect_probs, base_policy, action_lookup, logger):
        for act in range(self.action_space.n):
            logger.record(
                f"policy/shielded {action_lookup[act]}",
                float(mass.probs[0][act]),
            )
        # if object_detect_probs.get("num_rejected_samples") is not None:
        #     logger.record(
        #         f"rollout/num_rejected_samples",
        #         float(object_detect_probs.get("num_rejected_samples")),
        #     )
        if object_detect_probs.get("alpha") is not None:
            logger.record(
                f"safety/alpha",
                float(object_detect_probs.get("alpha")),
            )
        # for direction in [0, 1, 2, 3]:  # TODO: order matters: use a map
        #     if "prob_box_prior" in object_detect_probs:
        #         logger.record(
        #             f"prob/prob_box_prior_{direction}",
        #             float(object_detect_probs["prob_box_prior"][0][direction]),
        #         )
        #     if "prob_corner_prior" in object_detect_probs:
        #         logger.record(
        #             f"prob/prob_corner_prior_{direction}",
        #             float(object_detect_probs["prob_corner_prior"][0][direction]),
        #         )
        #     if "prob_box_posterior" in object_detect_probs:
        #         logger.record(
        #             f"prob/prob_box_posterior_{direction}",
        #             float(object_detect_probs["prob_box_posterior"][0][direction]),
        #         )
        #         error_box_posterior = (
        #             object_detect_probs["ground_truth_box"]
        #             - object_detect_probs["prob_box_posterior"]
        #         ).abs()
        #         logger.record(
        #             f"error/error_box_posterior_{direction}",
        #             float(error_box_posterior[0][direction]),
        #         )
        #     if "prob_corner_posterior" in object_detect_probs:
        #         logger.record(
        #             f"prob/prob_corner_posterior_{direction}",
        #             float(object_detect_probs["prob_corner_posterior"][0][direction]),
        #         )
        #         error_corner_posterior = (
        #             object_detect_probs["ground_truth_corner"]
        #             - object_detect_probs["prob_corner_posterior"]
        #         ).abs()
        #         logger.record(
        #             f"error/error_corner_posterior_{direction}",
        #             float(error_corner_posterior[0][direction]),
        #         )

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

    def evaluate_safety_shielded(self, obs: th.Tensor):
        with th.no_grad():
            _, _, _, mass, (object_detect_probs, base_policy) = self.forward(obs)
            return self.get_step_safety(
                mass.probs,
                object_detect_probs["ground_truth_box"],
                object_detect_probs["ground_truth_corner"],
            )

    def forward(self, x, deterministic: bool = False):
        """
        Forward pass in all the networks (actor and critic)

        :param obs: Observation
        :param deterministic: Whether to sample or use deterministic actions
        :return: action, value and log probability of the action
        """

        obs = self.image_encoder(x)
        latent_pi, latent_vf, latent_sde = self._get_latent(obs)
        # Evaluate the values for the given observations
        values = self.value_net(latent_vf)
        distribution = self._get_action_dist_from_latent(latent_pi, latent_sde=latent_sde)
        base_actions = distribution.distribution.probs

        with th.no_grad():
            ground_truth_box = get_ground_truth_of_box(
                input=x, agent_colors=PLAYER_COLORS, box_colors=BOX_COLORS,
            )
            ground_truth_corner = get_ground_truth_of_corners(
                input=x, agent_colors=PLAYER_COLORS, obsacle_colors=OBSTABLE_COLORS, floor_color=FLOOR_COLOR,
            )
            boxes = ground_truth_box
            corners = ground_truth_corner
            object_detect_probs = {
                "ground_truth_box": ground_truth_box,
                "ground_truth_corner": ground_truth_corner,
            }
            # if not th.all(ground_truth_corner == 0):
            #     k=1

        if self.alpha == 0:
            actions = distribution.get_actions(deterministic=deterministic)
            log_prob = distribution.log_prob(actions)
            object_detect_probs["alpha"] = 0
            return (actions, values, log_prob, distribution.distribution, [object_detect_probs, base_actions])

        if not self.differentiable_shield and self.alpha == 1:
            num_rejected_samples = 0
            while True:
                actions = distribution.get_actions(deterministic=deterministic)
                with th.no_grad():
                    # Using problog to model check
                    results = self.query_safety_layer(
                        x={
                            "box": boxes,
                            "corner": corners,
                            "action": th.eye(self.n_actions)[actions],
                        }
                    )
                safe_next = results["safe_next"]
                if not th.any(safe_next.isclose(th.zeros(actions.shape))):
                    break
                else:
                    num_rejected_samples += 1
            log_prob = distribution.log_prob(actions)
            object_detect_probs["num_rejected_samples"] = num_rejected_samples
            object_detect_probs["alpha"] = 1
            # object_detect_probs["too_many_rejected_samples"] = num_rejected_samples > 10000
            return (actions, values, log_prob, distribution.distribution, [object_detect_probs, base_actions])

        if self.differentiable_shield:
            results = self.dpl_layer(
                x={
                    "box": boxes,
                    "corner": corners,
                    "action": base_actions,
                }
            )
            # Combine safest policy and base_policy
            if self.alpha == "one_minus_safety":
                safety = self.get_step_safety(base_actions, boxes, corners)
                alpha = (1 - safety)
            elif self.alpha == "learned":
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
            # Combine safest policy and base_policy
            if self.alpha == "one_minus_safety":
                safety = self.get_step_safety(base_actions, boxes, corners)
                alpha = (1 - safety)
            elif self.alpha == "learned":
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
        # # NO Shielding
        # if not self.shield:
        #     return self.no_shielding(distribution, values, x, deterministic)
        # # SOFT Shielding
        # elif self.shield and "sokoban_corner2_.pl" in self.program_path:
        #     return self.soft_shielding(distribution, values, obs, x, deterministic)
        # elif "alpha" in self.program_path:
        #     return self.soft_shielding_alpha(distribution, values, obs, x, deterministic)
        # # HARD Shielding
        # else:
        #     return self.hard_shielding(distribution, values, obs, x, deterministic)

    def no_shielding(self, distribution, values, x, deterministic):
        actions = distribution.get_actions(deterministic=deterministic)
        log_prob = distribution.log_prob(actions)
        with th.no_grad():
            ground_truth_box = get_ground_truth_of_box(
                input=x,
                agent_colors=PLAYER_COLORS,
                box_colors=BOX_COLORS,
            )
            ground_truth_corner = get_ground_truth_of_corners(
                input=x,
                agent_colors=PLAYER_COLORS,
                obsacle_colors=OBSTABLE_COLORS,
                floor_color=FLOOR_COLOR,
            )

            base_actions = distribution.distribution.probs

            object_detect_probs = {
                "ground_truth_box": ground_truth_box,
                "ground_truth_corner": ground_truth_corner,
            }

        return (
            actions,
            values,
            log_prob,
            distribution.distribution,
            [object_detect_probs, base_actions],
        )


    def soft_shielding_alpha(self, distribution, values, obs, x, deterministic):
        with th.no_grad():
            ground_truth_box = get_ground_truth_of_box(
                input=x,
                agent_colors=PLAYER_COLORS,
                box_colors=BOX_COLORS,
            )

            ground_truth_corner = get_ground_truth_of_corners(
                input=x,
                agent_colors=PLAYER_COLORS,
                obsacle_colors=OBSTABLE_COLORS,
                floor_color=FLOOR_COLOR,
            )
            # boxes = self.box_layer(obs)
            # corners = self.corner_layer(obs)
            boxes = ground_truth_box
            corners = ground_truth_corner

        base_actions = distribution.distribution.probs
        results = self.dpl_layer(
            x={
                "box": boxes,
                "corner": corners,
                "action": base_actions,
            }
        )
        actions = results["safe_action"]

        actions = self.alpha * base_actions + (1 - self.alpha) * actions

        mass = Categorical(probs=actions)
        if not deterministic:
            actions = mass.sample()
        else:
            actions = th.argmax(mass.probs,dim=1)

        log_prob = mass.log_prob(actions)

        with th.no_grad():
            object_detect_probs = {
                "prob_box_prior": boxes,
                "prob_corner_prior": corners,
                "prob_box_posterior": ground_truth_box,
                "prob_corner_posterior": ground_truth_corner,
                "ground_truth_box": ground_truth_box,
                "ground_truth_corner": ground_truth_corner,
            }

        return (actions, values, log_prob, mass, [object_detect_probs, base_actions])

    def soft_shielding(self, distribution, values, obs, x, deterministic):
        with th.no_grad():
            ground_truth_box = get_ground_truth_of_box(
                input=x,
                agent_colors=PLAYER_COLORS,
                box_colors=BOX_COLORS,
            )

            ground_truth_corner = get_ground_truth_of_corners(
                input=x,
                agent_colors=PLAYER_COLORS,
                obsacle_colors=OBSTABLE_COLORS,
                floor_color=FLOOR_COLOR,
            )
            # boxes = self.box_layer(obs)
            # corners = self.corner_layer(obs)
            boxes = ground_truth_box
            corners = ground_truth_corner

        base_actions = distribution.distribution.probs
        results = self.dpl_layer(
            x={
                "box": boxes,
                "corner": corners,
                "action": base_actions,
                "free_action": base_actions
            }
        )
        actions = results["safe_action"]

        mass = Categorical(probs=actions)
        if not deterministic:
            actions = mass.sample()
        else:
            actions = th.argmax(mass.probs,dim=1)

        log_prob = mass.log_prob(actions)

        with th.no_grad():
            object_detect_probs = {
                "prob_box_prior": boxes,
                "prob_corner_prior": corners,
                "prob_box_posterior": ground_truth_box,
                "prob_corner_posterior": ground_truth_corner,
                "ground_truth_box": ground_truth_box,
                "ground_truth_corner": ground_truth_corner,
            }

        return (actions, values, log_prob, mass, [object_detect_probs, base_actions])

    def hard_shielding(self, distribution, values, obs, x, deterministic):
        with th.no_grad():
            ground_truth_box = get_ground_truth_of_box(
                input=x,
                agent_colors=PLAYER_COLORS,
                box_colors=BOX_COLORS,
            )

            ground_truth_corner = get_ground_truth_of_corners(
                input=x,
                agent_colors=PLAYER_COLORS,
                obsacle_colors=OBSTABLE_COLORS,
                floor_color=FLOOR_COLOR,
            )
            boxes = ground_truth_box
            corners = ground_truth_corner

        base_actions = distribution.distribution.probs
        results = self.dpl_layer(
            x={
                "box": boxes,
                "corner": corners,
                "action": base_actions,
            }
        )

        # For when we set safe_action=true as evidence
        actions = results["safe_action"]

        mass = Categorical(probs=actions)
        if not deterministic:
            actions = mass.sample()
        else:
            actions = th.argmax(mass.probs,dim=1)

        log_prob = mass.log_prob(actions)
        with th.no_grad():
            object_detect_probs = {
                "prob_box_prior": boxes,
                "prob_corner_prior": corners,
                "prob_box_posterior": boxes,
                "prob_corner_posterior": corners,
                "ground_truth_box": ground_truth_box,
                "ground_truth_corner": ground_truth_corner,
            }

        return (
            actions,
            values,
            log_prob,
            mass,
            [object_detect_probs, base_actions]
        )

    def evaluate_actions(
        self, obs: th.Tensor, actions: th.Tensor
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
            latent_pi, latent_vf, latent_sde = self._get_latent(obs)
            distribution = self._get_action_dist_from_latent(latent_pi, latent_sde)
            log_prob = distribution.log_prob(actions)
            values = self.value_net(latent_vf)
            return values, log_prob, distribution.entropy()

        _, values, _, mass, _ = self.forward(obs)
        log_prob = mass.log_prob(actions)
        return values, log_prob, mass.entropy()

    def _predict(self, observation: th.Tensor, deterministic: bool = False) -> th.Tensor:
        with th.no_grad():
            _actions, values, log_prob, mass, _  = self.forward(observation, deterministic)
            return _actions