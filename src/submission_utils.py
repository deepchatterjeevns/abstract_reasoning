import json
import multiprocessing
import os
import time
import pandas as pd

from src.preprocessing import preprocess_sample
from src.utils import show_sample, matrix2answer
import matplotlib as mpl
from matplotlib import pyplot as plt

from tqdm.notebook import tqdm
from functools import partial


def process_file(
    file_path,
    PATH,
    predictors,
    preprocess_params=None,
    color_params=None,
    show_results=True,
    break_after_answer=False,
    queue=None,
):
    with open(os.path.join(PATH, file_path), "r") as file:
        sample = json.load(file)

    submission_list = []
    sample = preprocess_sample(
        sample, params=preprocess_params, color_params=color_params
    )

    for predictor in predictors:
        result, answer = predictor(sample)
        if result == 0:
            if show_results:
                show_sample(sample)

            for j in range(len(answer)):
                answers = set([])
                for k in range(len(answer[j])):
                    str_answer = matrix2answer(answer[j][k])
                    if str_answer not in answers:
                        if show_results and k < 3:
                            plt.matshow(
                                answer[0][k],
                                cmap="Set3",
                                norm=mpl.colors.Normalize(vmin=0, vmax=9),
                            )
                            plt.show()
                            print(file_path, str_answer)
                        answers.add(str_answer)
                        submission_list.append(
                            {
                                "output_id": file_path[:-5] + "_" + str(j),
                                "output": str_answer,
                            }
                        )

            if break_after_answer:
                break
    if queue is not None:
        queue.put(submission_list)


def run_parallel(
    files_list,
    PATH,
    predictors,
    preprocess_params=None,
    color_params=None,
    show_results=True,
    break_after_answer=False,
    processes=20,
    timeout=10,
):
    process_list = []
    timing_list = []

    queue = multiprocessing.Queue(10000)
    func = partial(
        process_file,
        PATH=PATH,
        predictors=predictors,
        preprocess_params=preprocess_params,
        color_params=color_params,
        show_results=show_results,
        break_after_answer=break_after_answer,
        queue=queue,
    )

    with tqdm(total=len(files_list)) as pbar:
        num_finished_previous = 0
        try:
            while True:

                num_finished = 0
                for process, start_time in zip(process_list, timing_list):
                    if process.is_alive():
                        if time.time() - start_time > timeout:
                            process.terminate()
                            process.join(0.1)
                            print("Time out. The process is killed.")
                            num_finished += 1

                    else:
                        num_finished += 1

                if num_finished == len(files_list):
                    pbar.reset()
                    pbar.update(len(files_list))
                    time.sleep(0.1)
                    break
                elif len(process_list) - num_finished < processes and len(
                    process_list
                ) < len(files_list):
                    p = multiprocessing.Process(
                        target=func, args=(files_list[len(process_list)],)
                    )
                    process_list.append(p)
                    timing_list.append(time.time())
                    p.start()
                pbar.update(num_finished - num_finished_previous)
                num_finished_previous = num_finished
                print(f"num_finished: {num_finished}, total_num: {len(process_list)}")
                time.sleep(1)
        except KeyboardInterrupt:
            for process in process_list:
                process.terminate()
                process.join(0.1)
            print("Got Ctrl+C")
        except Exception as error:
            for process in process_list:
                process.terminate()
                process.join(0.1)
            print(f"Function raised {error}")
    result = []
    while not queue.empty():
        result = result + queue.get()
    return result


def generate_submission(
    predictions_list, sample_submission_path="data/sample_submission.csv"
):
    submission = pd.read_csv(sample_submission_path).to_dict("records")

    initial_ids = set([data["output_id"] for data in submission])
    new_submission = []

    ids = set([data["output_id"] for data in predictions_list])
    for output_id in ids:
        predicts = list(
            set(
                [
                    data["output"]
                    for data in predictions_list
                    if data["output_id"] == output_id
                ]
            )
        )
        output = " ".join(predicts[:3])
        new_submission.append({"output_id": output_id, "output": output})

    for output_id in initial_ids:
        if not output_id in ids:
            new_submission.append({"output_id": output_id, "output": ""})

    return pd.DataFrame(new_submission)


def combine_submission_files(
    list_of_dfs, sample_submission_path="data/sample_submission.csv"
):
    submission = pd.read_csv(sample_submission_path)

    list_of_outputs = []
    for df in list_of_dfs:
        list_of_outputs.append(
            df.sort_values(by="output_id")["output"].astype(str).values
        )

    merge_output = []
    for i in range(len(list_of_outputs[0])):
        list_of_answ = [
            [x.strip() for x in output[i].strip().split(" ")]
            for output in list_of_outputs
        ]

        total_len = len(
            list(set([item for sublist in list_of_answ for item in sublist]))
        )
        while total_len > 3:
            n = 0
            for i in range(1, len(list_of_answ) + 1):
                if len(list_of_answ[-i]) > (i > len(list_of_answ) - 3):
                    list_of_answ[-i] = list_of_answ[-i][:-1]
                    break
            list_of_answ[n] = list_of_answ[n][:-1]
            total_len = len(
                list(set([item for sublist in list_of_answ for item in sublist]))
            )

        o = list(set([item for sublist in list_of_answ for item in sublist]))
        answer = " ".join(o[:3]).strip()
        while answer.find("  ") > 0:
            answer = answer.replace("  ", " ")
        merge_output.append(o)
    submission["output"] = merge_output
    submission["output"] = submission["output"].astype(str)
    return submission