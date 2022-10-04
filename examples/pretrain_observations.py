import os
from pls.workflows.pre_train import generate_random_images_gf, generate_random_images_sokoban, generate_random_images_cr
from pls.workflows.execute_workflow import pretrain_observation_gf, pretrain_observation_sokoban
from dask.distributed import Client
from pls.observation_nets.observation_nets import Observation_net, Observation_Net_Stars, Observation_Net_Sokoban


def generate_cr(num_imgs):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    img_folder = os.path.join(dir_path, "../pls/data/carracing")

    csv_file = os.path.join(img_folder, "labels.csv")
    if not os.path.exists(img_folder):
        os.makedirs(img_folder)
    generate_random_images_cr(csv_file, img_folder, num_imgs)

def generate_gf(num_imgs):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    img_folder = os.path.join(dir_path, "../pls/data/gf_small")

    csv_file = os.path.join(img_folder, "labels.csv")
    if not os.path.exists(img_folder):
        os.makedirs(img_folder)
    generate_random_images_gf(csv_file, img_folder, num_imgs)

def generate_sokoban(num_imgs):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    img_folder = os.path.join(dir_path, "../pls/data/sokoban")
    csv_file = os.path.join(img_folder, "labels.csv")

    if not os.path.exists(img_folder):
        os.makedirs(img_folder)
    generate_random_images_sokoban(csv_file, img_folder, num_imgs)

def pre_train_gf(n_train, net_class, epochs, downsampling_size=None):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    img_folder = os.path.join(dir_path, "../pls/data/gf_small")

    csv_file = os.path.join(img_folder, "labels.csv")
    if not os.path.exists(img_folder):
        os.makedirs(img_folder)

    model_folder = os.path.join(dir_path, "../experiments_trials3/goal_finding/small/data/")
    if not os.path.exists(model_folder):
        os.makedirs(model_folder)

    image_dim = 482
    pretrain_observation_gf(csv_file=csv_file, img_folder=img_folder, model_folder=model_folder,
                            image_dim=image_dim, downsampling_size=downsampling_size,
                            n_train=n_train, epochs=epochs, net_class=net_class)

def pre_train_sokoban(n_train, net_class, epochs, downsampling_size=None):
    dir_path = os.path.dirname(os.path.realpath(__file__))
    img_folder = os.path.join(dir_path, "../pls/data/sokoban")

    csv_file = os.path.join(img_folder, "labels.csv")
    if not os.path.exists(img_folder):
        os.makedirs(img_folder)

    model_folder = os.path.join(dir_path, "../experiments_trials3/sokoban/2box1map/data/")
    if not os.path.exists(model_folder):
        os.makedirs(model_folder)

    image_dim = 160
    pretrain_observation_sokoban(csv_file=csv_file, img_folder=img_folder, model_folder=model_folder,
                            image_dim=image_dim, downsampling_size=downsampling_size,
                            n_train=n_train, epochs=epochs, net_class=net_class)


def main_cluster():
    client = Client("134.58.41.100:8786")

    # with performance_report(filename="dask-report.html"):
    ## some dask computation
    futures = client.submit(generate_gf)
    # results = client.gather(futures)

if __name__ == "__main__":
    # generate_gf(num_imgs=1100)
    # pre_train_gf(n_train=1000, net_class=Observation_Net_Stars, downsampling_size=8, epochs=10000)
    # generate_sokoban(num_imgs=3100)
    # pre_train_sokoban(n_train=1000, net_class=Observation_Net_Sokoban, downsampling_size=4, epochs=10)
    generate_cr(num_imgs=1100)
    # main_cluster()

