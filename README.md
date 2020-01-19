# Neurosmash

Project for course "Neural Information Processing Systems" 2019. 


## Reproducability
To reproduce our experiments, various steps have to be taken. Please take into account that for steps 1 and 4, an active environment is required and the settings (such as the port number) should be equal to those
in the code.

1. A training set for our VAE has to be generated by running get_data.
2. Run VAE_train to generate two models, first being the VAE without a weighted loss function and the second being the VAE with a weighted loss function.
3. Run rnn_VAE.py with the correct VAE model parameters specificied at the top of the file.
4. The final step consists of training our controller (i.e. DQN) and is done by running pipeline_DQN. For this we performed four experiments:
    1. Vanilla DQN can be trained by changing the hyperparameters: USE_WM=False, ZERO_INPUT=False
    2. World Models can be trained by changing the hyperparameters: USE_WM=True, USE_RNN=True, ZERO_INPUT=False
    3. Zero input model without RNN can be trained by changing the hyperparameters: USE_WM=True, USE_RNN=False, ZERO_INPUT=True
    4. Zero input model with RNN can be trained by changing the hyperparameters: USE_WM=True, USE_RNN=True, ZERO_INPUT=True

<!-- 
## Environment


## Methods

### World Models

#### VAE

We're using a VAE to encode the inputs into a lower dimensional space

#### Mixture Density RNN

The MD RNN will capture the dynamics of the environment.

### RL Optimization


## Further Reading -->
