import os
import argparse
import subprocess
import numpy as np
import ray
from ray import tune
from ray.tune.config_parser import make_parser
from ray.tune.experiment import Experiment

import misc
from policies import PolicyManager
from trainers import get_trainer_class


from ray.rllib.utils.framework import try_import_torch
torch, nn = try_import_torch()
torch.backends.cudnn.enabled = False # HACKY


def parse_args():
    # Set default arguments based on https://github.com/ray-project/ray/blob/master/python/ray/tune/config_parser.py
    parser = make_parser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description='Train a reinforcement learning agent.')
    parser.add_argument(
        '-f',
        '--config-file',
        default=None,
        type=str,
        help='Use config options from this file. Note that this.')
    parser.add_argument(
        '--temp-dir',
        default='~/tmp',
        type=str,
        help='Directory for temporary files generated by ray.')
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Whether to attempt to resume previous Tune experiments.')
    parser.add_argument(
        '-v', action='store_true', help='Whether to use INFO level logging.')
    parser.add_argument(
        '-vv', action='store_true', help='Whether to use DEBUG level logging.')
    parser.add_argument(
        '--local-mode',
        action='store_true',
        help='Whether to run ray with `local_mode=True`. '
             'Only if --ray-num-nodes is not used.')
    parser.set_defaults(max_failures=1) # overwrite default value
    
    args = parser.parse_args()

    return args


def main():
    # Get experiment configuration
    args = parse_args()
    experiments = misc.load_yaml(args.config_file)
    exp_names = list(experiments.keys())
    assert len(exp_names) == 1
    exp = experiments[exp_names[0]]
    exp['trial_name_creator'] = trial_name_creator
    path_keys = ['local_dir']
    for k in path_keys:
        path = misc.get_dict_value_by_str(exp, k)
        path = os.path.abspath(os.path.expanduser(path))
        misc.set_dict_value_by_str(exp, k, path)
    verbose = 1
    if args.v:
        exp['config']['log_level'] = 'INFO'
        verbose = 2
    if args.vv:
        exp['config']['log_level'] = 'DEBUG'
        verbose = 3
    if args.local_mode:
        exp['config']['num_workers'] = 0

    # TODO: Copy config file

    # Register custom model and environments
    env_creator = misc.register_custom_env(exp['env'])
    if exp['run'] == 'PPO':
        misc.register_custom_model(exp['config']['model'])
    elif exp['run'] == 'CustomSAC':
        misc.register_custom_model(exp['config']['Q_model'], register_action_dist=False)
        misc.register_custom_model(exp['config']['policy_model'], register_action_dist=False)

        exp['config']['buffer_size'] = int(exp['config']['buffer_size'])
    else:
        raise NotImplementedError('Unrecognized algorithm {}'.format(exp['run']))

    # Start ray (earlier to accomodate in-the-env agent)
    args.temp_dir = os.path.abspath(os.path.expanduser(args.temp_dir))
    ray.init(
        local_mode=args.local_mode,
        _temp_dir=args.temp_dir,
        include_dashboard=False,
        num_cpus=exp['ray_resources']['num_cpus'],
        num_gpus=exp['ray_resources']['num_gpus'])

    # Set callbacks (should be prior to setting mult-agent attribute)
    policy_manager = PolicyManager(env_creator, exp['config'])
    if 'callbacks' in exp['config'].keys():
        agent_ids = policy_manager.env.agent_ids
        misc.set_callbacks(exp, agent_ids)

    # Setup multi-agent
    if 'multiagent' in exp['config'].keys():
        policy_ids = exp['config']['multiagent']['policies']
        exp['config']['multiagent']['policies'] = dict()
        for p_id in policy_ids:
            exp['config']['multiagent']['policies'][p_id] = policy_manager.get_policy(p_id)
        exp['config']['multiagent']['policy_mapping_fn'] = policy_manager.get_policy_mapping_fn(
            exp['config']['multiagent']['policy_mapping_fn'])

    # handle hyperparameter tuning NOTE: not working yet
    if exp['run'] == 'PPO':
        tune_keys = ['lr', 'num_sgd_iter', 'train_batch_size', 'sgd_minibatch_size', 'vf_loss_coeff', 
                    'vf_clip_param', 'entropy_coeff', 'kl_coeff', 'kl_target', 'clip_param']
        for k, v in exp['config'].items():
            if k in tune_keys and isinstance(v, list):
                exp['config'][k] = tune.grid_search(v)

    # Convert to Experiment object
    exp['config']['env'] = exp["env"] # move env inside config to follow Experiment format
    del exp['env']
    exp['restore'] = None if 'restore' not in exp.keys() else exp['restore']
    exp['keep_checkpoints_num'] = None if 'keep_checkpoints_num' not \
        in exp.keys() else exp['keep_checkpoints_num']
    exp['resources_per_trial'] = None if 'resources_per_trial' not \
        in exp.keys() else exp['resources_per_trial']

    # Get trainer
    trainer = get_trainer_class(exp['run'])
    if args.resume:
        misc.resume_from_latest_ckpt(exp, exp_names[0])

    # Run experiment
    tune.run(trainer,
             name=exp_names[0],
             stop=exp['stop'],
             config=exp['config'],
             resources_per_trial=exp['resources_per_trial'],
             num_samples=exp['num_samples'],
             local_dir=exp['local_dir'],
             keep_checkpoints_num=exp['keep_checkpoints_num'],
             checkpoint_freq=exp['checkpoint_freq'],
             checkpoint_at_end=exp['checkpoint_at_end'],
             verbose=verbose,
             trial_name_creator=exp['trial_name_creator'],
             restore=exp['restore'],
             )

    # End ray
    ray.shutdown()


def trial_name_creator(trial):
    githash = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).\
                                      strip().decode('utf-8')
    return str(trial) + '_' + githash


if __name__ == '__main__':
    main()
