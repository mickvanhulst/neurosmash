from VAE import VAE
from rnn_vae import MDNRNN
from controller_DQN import DQN, ReplayMemory, Transition
from torch.autograd import Variable
import matplotlib.pyplot as plt
import matplotlib
import torch
import math
import numpy as np
import Neurosmash
import random

import torch.nn.functional as F

# ---------- sep file.

BATCH_SIZE = 128
GAMMA = 0.999
EPS_START = 0.9
EPS_END = 0.05
EPS_DECAY = 200
TARGET_UPDATE = 10
n_actions = 3

def select_action(state):
    global steps_done
    sample = random.random()
    eps_threshold = EPS_END + (EPS_START - EPS_END) * \
        math.exp(-1. * steps_done / EPS_DECAY)
    steps_done += 1
    if sample > eps_threshold:
        with torch.no_grad():
            # t.max(1) will return largest column value of each row.
            # second column on max result is index of where max element was
            # found, so we pick action with the larger expected reward.
            return policy_net(state).max(1)[1].view(1, 1)
    else:
        return torch.tensor([[random.randrange(n_actions)]], device=device, dtype=torch.long)

episode_durations = []

is_ipython = 'inline' in matplotlib.get_backend()
if is_ipython:
    from IPython import display

plt.ion()


def plot_durations():
    plt.figure(2)
    plt.clf()
    durations_t = torch.tensor(episode_durations, dtype=torch.float)
    plt.title('Training...')
    plt.xlabel('Episode')
    plt.ylabel('Duration')
    plt.plot(durations_t.numpy())
    # Take 100 episode averages and plot them too
    if len(durations_t) >= 100:
        means = durations_t.unfold(0, 100, 1).mean(1).view(-1)
        means = torch.cat((torch.zeros(99), means))
        plt.plot(means.numpy())

    plt.pause(0.001)  # pause a bit so that plots are updated
    if is_ipython:
        display.clear_output(wait=True)
        display.display(plt.gcf())

# ------------------

learning_rate = 0.01
gamma = 0.99
# Setup
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
weighted_loss = 1

ip         = "127.0.0.1" # Ip address that the TCP/IP interface listens to
port       = 13000       # Port number that the TCP/IP interface listens to
size       = 64         # Please check the Updates section above for more details
timescale  = 10     # Please check the Updates section above for more details

env = Neurosmash.Environment(timescale=timescale, size=size, port=port, ip=ip)

# Load VAE weights
vae = VAE(device, image_channels=3).to(device)
vae.load_state_dict(torch.load("./data_folder_vae/vae_v3_weighted_loss_{}.torch".format(weighted_loss)))
vae.eval()

# Load RNN weights
rnn = MDNRNN(32, 256, 5, 1).to(device)
rnn.load_state_dict(torch.load("./rnn_29dec_{}.torch".format(weighted_loss)))
rnn.eval()

# Load controller
policy_net = DQN().to(device)
target_net = DQN().to(device)
target_net.load_state_dict(policy_net.state_dict())
target_net.eval()

optimizer = torch.optim.RMSprop(policy_net.parameters())
memory = ReplayMemory(10000)

steps_done = 0


def optimize_model():
    if len(memory) < BATCH_SIZE:
        return
    transitions = memory.sample(BATCH_SIZE)
    # Transpose the batch (see https://stackoverflow.com/a/19343/3343043 for
    # detailed explanation). This converts batch-array of Transitions
    # to Transition of batch-arrays.
    batch = Transition(*zip(*transitions))

    # Compute a mask of non-final states and concatenate the batch elements
    # (a final state would've been the one after which simulation ended)
    non_final_mask = torch.tensor(tuple(map(lambda s: s is not None,
                                          batch.next_state)), device=device)
    non_final_next_states = torch.cat([s for s in batch.next_state
                                                if s is not None])
    state_batch = torch.cat(batch.state)
    action_batch = torch.cat(batch.action)
    reward_batch = torch.cat(batch.reward)

    # Compute Q(s_t, a) - the model computes Q(s_t), then we select the
    # columns of actions taken. These are the actions which would've been taken
    # for each batch state according to policy_net
    state_action_values = policy_net(state_batch).gather(1, action_batch)

    # Compute V(s_{t+1}) for all next states.
    # Expected values of actions for non_final_next_states are computed based
    # on the "older" target_net; selecting their best reward with max(1)[0].
    # This is merged based on the mask, such that we'll have either the expected
    # state value or 0 in case the state was final.
    next_state_values = torch.zeros(BATCH_SIZE, device=device)
    next_state_values[non_final_mask] = target_net(non_final_next_states).max(1)[0].detach()
    # Compute the expected Q values
    expected_state_action_values = (next_state_values * GAMMA) + reward_batch

    # Compute Huber loss
    loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1))

    # Optimize the model
    optimizer.zero_grad()
    loss.backward()
    for param in policy_net.parameters():
        param.grad.data.clamp_(-1, 1)
    optimizer.step()

def process_state(state):
    visual = torch.FloatTensor(state).reshape(size, size, 3) / 255.0
    visual = visual.permute(2, 0, 1)
    encoded_visual = vae.encode(visual.reshape(1, 3, 64, 64).cuda())[0]
    # print(encoded_visual.shape)
    # 3 actions
    futures = []
    for i in range(3):
        action = torch.Tensor([i]).cuda()
        hidden = rnn.init_hidden(1)
        z = torch.cat([encoded_visual.reshape(1, 1, 32), action.reshape(1, 1, 1)], dim=2)
        # print(z.shape)
        (pi, mu, sigma), (hidden_future, _) = rnn(z, hidden)
        futures.append(hidden_future)

    futures = torch.cat(futures).reshape(3 * 256)
    state = torch.cat([encoded_visual.reshape(32), futures]).reshape(1, (32 + 3 * 256)).detach()
    action = select_action(state).detach()
    return state, action

def main(episodes):
    # based on: https://pytorch.org/tutorials/intermediate/reinforcement_q_learning.html
    reward_save = []
    # Episode lasts until end == 1
    wins = 0
    for episode in range(episodes):
        print("Episode: ", episode)
        end, reward, state_unprocessed = env.reset()  # Reset environment and record the starting state
        # Init state seems to be zeroes in tutorial; but then given that state, the env will probably select a
        # random action..?

        state, action = process_state(state_unprocessed)
        done = False
        # Go through every episode but only 15 timesteps
        for time in range(50):
            #TODO: Various sources do not take difference in states, although link above does. Idk if we should.
            done, reward, state_unprocessed = env.step(action)

            # Store previous state, then generate new state based.
            next_state, next_action = process_state(state_unprocessed)

            # Save reward
            if reward > 0:
                wins += 1
                print(reward)

            # Add to transition matrix: from prev_state to new state; given an action/reward.
            memory.push(state, action, next_state, torch.tensor(reward).reshape(1).to(device))

            # Get new transition state.
            state = next_state
            action = next_action

            # Optimize model.
            optimize_model()

            # Are we done?
            if done:
                reward_save.append(reward)
                break
            elif time == 49:
                reward_save.append(reward)

        # Print avg reawrd
        # Update the target network, copying all weights and biases in DQN
        if episode % TARGET_UPDATE == 0:
            target_net.load_state_dict(policy_net.state_dict())
            print('Win probability past {} episodes: {}'.format(TARGET_UPDATE, wins / TARGET_UPDATE))
            print('-----------------')
            wins = 0

    print('Complete')
    # plt.ioff()
    # plt.show()

    return reward_save

reward_sv = main(2000)
torch.save(reward_sv, "rewards_test_DQN")