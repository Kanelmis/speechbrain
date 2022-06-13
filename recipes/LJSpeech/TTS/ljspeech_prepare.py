"""
LJspeech data preparation.
Download: https://data.keithito.com/data/speech/LJSpeech-1.1.tar.bz2

Authors
 * Yingzhi WANG 2022
 * Sathvik Udupa 2022
"""

import os
import csv
import json
import shutil
import random
import logging
import subprocess
from speechbrain.dataio.dataio import (
    load_pkl,
    save_pkl,
    load_data_json
)

logger = logging.getLogger(__name__)
OPT_FILE = "opt_ljspeech_prepare.pkl"
METADATA_CSV = "metadata.csv"
TRAIN_JSON = "train.json"
VALID_JSON = "valid.json"
TEST_JSON = "test.json"
WAVS = "wavs"
DURATIONS = "durations"

logger = logging.getLogger(__name__)
OPT_FILE = "opt_ljspeech_prepare.pkl"

def prepare_ljspeech(
    data_folder,
    save_folder,
    splits=["train", "valid"],
    split_ratio=[90, 10],
    seed=1234,
    skip_prep=False,
    **kwargs
):
    """
    Prepares the csv files for the LJspeech datasets.

    Arguments
    ---------
    data_folder : str
        Path to the folder where the original VoxCeleb dataset is stored.
    save_folder : str
        The directory where to store the csv files.
    splits : list
        List of splits to prepare from ['train', 'valid']
    split_ratio : list
        List if int for train and validation splits
    skip_prep: Bool
        If True, skip preparation.
    seed : int
        Random seed

    Example
    -------
    >>> from recipes.VoxCeleb.voxceleb1_prepare import prepare_voxceleb
    >>> data_folder = 'data/LJspeech/'
    >>> save_folder = 'save/'
    >>> splits = ['train', 'valid']
    >>> split_ratio = [90, 10]
    >>> seed = 1234
    >>> prepare_voxceleb(data_folder, save_folder, splits, split_ratio, seed)
    """
    # setting seeds for reproducible code.
    random.seed(seed)

    if skip_prep:
        return
    # Create configuration for easily skipping data_preparation stage
    conf = {
        "data_folder": data_folder,
        "splits": splits,
        "split_ratio": split_ratio,
        "save_folder": save_folder,
        "seed": seed,
    }
    if not os.path.exists(save_folder):
        os.makedirs(save_folder)

    # Setting ouput files
    meta_csv = os.path.join(data_folder, METADATA_CSV)
    wavs_folder = os.path.join(data_folder, WAVS)

    save_opt = os.path.join(save_folder, OPT_FILE)
    save_json_train = os.path.join(save_folder, TRAIN_JSON)
    save_json_valid = os.path.join(save_folder, VALID_JSON)
    save_json_test = os.path.join(save_folder, TEST_JSON)

    if "duration_link" in kwargs:
        durations_folder = os.path.join(data_folder, "durations")
        if not os.path.exists(durations_folder):
            logger.info("Downloading durations for fastspeech training")
            subprocess.call(["wget","-q",   kwargs["duration_link"]])
            subprocess.call(["unzip", "-qq", "ljspeech_DFA_durations.zip"])
            subprocess.call(["mv", "durations", durations_folder])
            subprocess.call(["rm", "-r", "ljspeech_DFA_durations.zip"])
    else:
        durations_folder = None

    # Check if this phase is already done (if so, skip it)
    if skip(splits, save_folder, conf):
        logger.info("Skipping preparation, completed in previous run.")
        return

    # Additional check to make sure metadata.csv and wavs folder exists
    assert os.path.exists(meta_csv), "metadata.csv does not exist"
    assert os.path.exists(wavs_folder), "wavs/ folder does not exist"

    msg = "Creating json file for ljspeech Dataset.."
    logger.info(msg)

    data_split, meta_csv = split_sets(data_folder, splits, split_ratio)

    # Prepare csv
    if "train" in splits:
        prepare_json(
            data_split["train"], save_json_train, wavs_folder, meta_csv, durations_folder
        )
    if "valid" in splits:
        prepare_json(
            data_split["valid"], save_json_valid, wavs_folder, meta_csv, durations_folder
        )
    if "test" in splits:
        prepare_json(
            data_split["test"], save_json_test, wavs_folder, meta_csv, durations_folder)
    if "create_symbol_list" in kwargs:
        create_symbol_file(save_folder, save_json_train)
    save_pkl(conf, save_opt)


def skip(splits, save_folder, conf):
    """
    Detects if the ljspeech data_preparation has been already done.
    If the preparation has been done, we can skip it.

    Returns
    -------
    bool
        if True, the preparation phase can be skipped.
        if False, it must be done.
    """
    # Checking json files
    skip = True

    split_files = {
        "train": TRAIN_JSON,
        "valid": VALID_JSON,
        "test": TEST_JSON,
    }

    for split in splits:
        if not os.path.isfile(os.path.join(save_folder, split_files[split])):
            skip = False

    #  Checking saved options
    save_opt = os.path.join(save_folder, OPT_FILE)
    if skip is True:
        if os.path.isfile(save_opt):
            opts_old = load_pkl(save_opt)
            if opts_old == conf:
                skip = True
            else:
                skip = False
        else:
            skip = False
    return skip


def split_sets(data_folder, splits, split_ratio):
    """Randomly splits the wav list into training, validation, and test lists.
    Note that a better approach is to make sure that all the classes have the
    same proportion of samples for each session.

    Arguments
    ---------
    wav_list : list
        list of all the signals in the dataset
    split_ratio: list
        List composed of three integers that sets split ratios for train,
        valid, and test sets, respectively.
        For instance split_ratio=[80, 10, 10] will assign 80% of the sentences
        to training, 10% for validation, and 10% for test.

    Returns
    ------
    dictionary containing train, valid, and test splits.
    """
    meta_csv = os.path.join(data_folder, METADATA_CSV)
    csv_reader = csv.reader(
        open(meta_csv), delimiter="|", quoting=csv.QUOTE_NONE
    )

    meta_csv = list(csv_reader)

    index_for_sessions = []
    session_id_start = "LJ001"
    index_this_session = []
    for i in range(len(meta_csv)):
        session_id = meta_csv[i][0].split("-")[0]
        if session_id == session_id_start:
            index_this_session.append(i)
            if i == len(meta_csv) - 1:
                index_for_sessions.append(index_this_session)
        else:
            index_for_sessions.append(index_this_session)
            session_id_start = session_id
            index_this_session = [i]

    session_len = [len(session) for session in index_for_sessions]

    data_split = {}
    for i, split in enumerate(splits):
        data_split[split] = []
        for j in range(len(index_for_sessions)):
            if split == "train":
                random.shuffle(index_for_sessions[j])
                n_snts = int(session_len[j] * split_ratio[i] / sum(split_ratio))
                data_split[split].extend(index_for_sessions[j][0:n_snts])
                del index_for_sessions[j][0:n_snts]
            if split == "valid":
                if "test" in splits:
                    random.shuffle(index_for_sessions[j])
                    n_snts = int(
                        session_len[j] * split_ratio[i] / sum(split_ratio)
                    )
                    data_split[split].extend(index_for_sessions[j][0:n_snts])
                    del index_for_sessions[j][0:n_snts]
                else:
                    data_split[split].extend(index_for_sessions[j])
            if split == "test":
                data_split[split].extend(index_for_sessions[j])

    return data_split, meta_csv


def prepare_json(seg_lst, json_file, wavs_folder, csv_reader, durations_folder):
    """
    Creates json file given a list of indexes.

    Arguments
    ---------
    seg_list : list
        The list of json indexes of a given data split.
    json_file : str
        Output json path
    wavs_folder : str
        LJspeech wavs folder
    csv_reader : _csv.reader
        LJspeech metadata

    Returns
    -------
    None
    """
    json_dict = {}
    for index in seg_lst:
        id = list(csv_reader)[index][0]
        wav = os.path.join(wavs_folder, f"{id}.wav")
        label = list(csv_reader)[index][2]
        json_dict[id] = {
            "wav": wav,
            "label": label,
            "segment": True if "train" in json_file else False,
        }
        if durations_folder is not None:
            duration_path = os.path.join(durations_folder, id+'.npy')
            json_dict[id].update({"durations":duration_path})

    # Writing the dictionary to the json file
    with open(json_file, mode="w") as json_f:
        json.dump(json_dict, json_f, indent=2)

    logger.info(f"{json_file} successfully created!")

def create_symbol_file(save_folder, save_json_train):
    lexicon_path = os.path.join(save_folder, "lexicon")
    if os.path.exists(lexicon_path):
        logger.info('Symbols file present')
    else:
        logger.info('Symbols file not present, creating from training data.')
        data = load_data_json(save_json_train)
        char_set = set()
        for id in data:
            line = data[id]['label']
            char_set.update(*line.lower())
        with open(lexicon_path, 'w') as f:
            f.write('\t'.join(char_set))