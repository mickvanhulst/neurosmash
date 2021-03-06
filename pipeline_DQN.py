from VAE import VAE
from rnn_vae import MDNRNN
from controller_DQN import ReplayMemory, Transition, DQN2, DQN_VAE
import matplotlib.pyplot as plt
import torch
import math
import Neurosmash
import random
import copy

import torch.nn.functional as F

torch.manual_seed(42)

'''
Code based on https://pytorch.org/tutorials/intermediate/reinforcement_q_learning.html
credits for providing example VAE model go to respective author.
'''

USE_WM = True
USE_RNN = True
ZERO_INPUT = False

BATCH_SIZE = 64
GAMMA = 0.99
EPS_START = 0.9
EPS_END = 0.01
EPS_DECAY = 200
TARGET_UPDATE = 10
n_actions = 3

learning_rate = 1e-2

# gamma = 0.99
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
rnn.load_state_dict(torch.load("./weights/rnn_29dec_{}.torch".format(weighted_loss)))
rnn.eval()

# Load controller, if vanilla DQN, replace DQN_VAE with DQN2

if USE_WM:
    if USE_RNN:
        input_params = n_actions*256 + 32
    else:
        input_params = 32
    policy_net = DQN_VAE(64, 64, 3, input_params).to(device)
    target_net = DQN_VAE(64, 64, 3, input_params).to(device)
else:
    policy_net = DQN2(64, 64, 3).to(device)
    target_net = DQN2(64, 64, 3).to(device)
target_net.load_state_dict(policy_net.state_dict())
target_net.eval()

optimizer = torch.optim.RMSprop(policy_net.parameters(), lr=learning_rate)
memory = ReplayMemory(10000)

steps_done = 0

def select_action(state):
    global steps_done
    sample = random.random()
    eps_threshold = EPS_END + (EPS_START - EPS_END) * \
        math.exp(-1. * steps_done / EPS_DECAY)
    steps_done += 1
    if (sample > eps_threshold):
        with torch.no_grad():
            # t.max(1) will return largest column value of each row.
            # second column on max result is index of where max element was
            # found, so we pick action with the larger expected reward.
            return policy_net(state).max(1)[1].view(1, 1)
    else:
        return torch.tensor([[random.randrange(n_actions)]], device=device, dtype=torch.long)

def plot_durations(wins_prob_list):
    plt.figure(2)
    plt.clf()
    episode_wins = torch.tensor(wins_prob_list, dtype=torch.float)
    torch.save(episode_wins, "DQN_vanilla.data")
    plt.title('Training...')
    plt.xlabel('Episode')
    plt.ylabel('Avg win probability')
    plt.plot(episode_wins.numpy())
    # Take 100 episode averages and plot them too
    if len(episode_wins) >= 100:
        means = episode_wins.unfold(0, 100, 1).mean(1).view(-1)
        means = torch.cat((torch.zeros(99), means))
        plt.plot(means.numpy())
    plt.ylim(0, 1)
    plt.savefig('./DQN_vanilla.png')
    plt.pause(0.001)  # pause a bit so that plots are updated

def optimize_model():
    '''
    Optimizes model by sampling from replay buffer.
    '''
    if len(memory) < BATCH_SIZE:
        return 0
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
    # target = (reward_batch + GAMMA * next_state_values).data
    # loss = (state_action_values - target).pow(2).mean().to(device)

    # Optimize the model
    optimizer.zero_grad()
    loss.backward()
    tot_grad = 0.0

    for i, param in enumerate(policy_net.parameters()):
        param.grad.data.clamp_(-1, 1)
        tot_grad += torch.sum(param.grad.data)

    if tot_grad == 0.0:
        print('GRADIENT IS ZERO')
    optimizer.step()
    return loss.item()

def process_state(state, t, world_models=False, use_rnn=True, zero_input=False):
    '''
    Processes state
    1. If world_models, thenstate is encoded by the VAE and
    a future state is predicted by the RNN. 
    2. If use_rnn, future predictions are made by RNN.
    3. IF zero_input, visual is multiplied by zero.
    '''
    visual = torch.FloatTensor(state).reshape(size, size, 3) / 255.0 * (0.0 if zero_input else 1.0)
    visual = visual.permute(2, 0, 1)
    
    if world_models:
        encoded_visual = vae.encode(visual.reshape(1, 3, 64, 64).cuda())[0]

        # 3 actions
        if use_rnn:
            futures = []
            for i in range(3):
                action = torch.Tensor([i]).cuda()
                hidden = rnn.init_hidden(1)
                z = torch.cat([encoded_visual.reshape(1, 1, 32), action.reshape(1, 1, 1)], dim=2)
                # print(z.shape)
                (pi, mu, sigma), (hidden_future, _) = rnn(z, hidden)
                futures.append(hidden_future)

            futures = torch.zeros(3*256).cuda()
            state = torch.cat([encoded_visual.reshape(32), futures]).reshape(1, (32 + 3 * 256)).detach()
        else:
            state = encoded_visual.reshape(1, 32).detach()
        action = select_action(state).detach()
    else:
        state = visual.reshape(1, 3, 64, 64).to(device)
        action = select_action(state).detach()
    return state, action

def adjust_learning_rate():
    global optimizer
    print('Reducing learning rate')
    for param_group in optimizer.param_groups:
        param_group['lr'] *= 0.1
        print(param_group['lr'])
    print('------------------------')

def main(episodes):
    # Episode lasts until end == 1
    wins_prob_list = []
    total_wins = 0
    max_t = 500
    cnt_updated = 0
    cnt_wins_losses = 0

    batch = []
    while cnt_wins_losses < episodes:
        print('Starting episode {}'.format(cnt_wins_losses))
        prev_weights = copy.deepcopy(policy_net)
        end, r, state_unprocessed = env.reset()  # Reset environment and record the starting state
        # Init state seems to be zeroes in tutorial; but then given that state, the env will probably select a
        # random action..?
        total_loss = 0

        state, action = process_state(state_unprocessed, 0, world_models=USE_WM, use_rnn=USE_RNN, zero_input=ZERO_INPUT)
        for t in range(max_t):
            done, r, state_unprocessed = env.step(action)


            # Store previous state, then generate new state based.
            next_state, next_action = process_state(state_unprocessed, t+1, world_models=USE_WM, use_rnn=USE_RNN, zero_input=ZERO_INPUT)

            if done:
                next_state = None

            # Add to batch
            batch.append([state, action, next_state, torch.tensor(r * 1.0).reshape(1).to(device)])

            # Get new transition state.
            state = next_state
            action = next_action

            # Only append and train if win/loss; do not count
            # draws as we do not want states where the user
            # gets stuck due to buggy environment.
            if done:
                if r > 0:
                    total_wins += 1

                for i, (state, action, next_state, reward) in enumerate(batch):
                    if i == (len(batch)-1):
                        print('Adding reward: {}'.format(reward))
                    memory.push(state, action, next_state, reward)
                    # Optimize model.
                    loss = optimize_model()
                    total_loss += loss

                cnt_wins_losses += 1
                wins_prob_list.append(total_wins / cnt_wins_losses)
                plot_durations(wins_prob_list)


                print('End episode {}, average {}, reward {}, done {}, avg loss {}'.format(cnt_wins_losses,
                                                                              wins_prob_list[-1],
                                                                              r,
                                                                              done,
                                                                              total_loss / t))
                print('Size of batch', len(batch))
                print('Number of memory slots filled: ', len(memory))
                print('-----------------')

                if cnt_wins_losses == 500:
                    # Reduce LR
                    adjust_learning_rate()
                if cnt_wins_losses % TARGET_UPDATE == 0:
                    target_net.load_state_dict(policy_net.state_dict())
                    torch.save(policy_net.state_dict(), './DQN_vanilla.pt')

            if done or (t == (max_t-1)):
                # reset batch and env.
                batch = []
                break

main(2000)