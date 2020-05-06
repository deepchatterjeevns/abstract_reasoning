import numpy as np
from src.preprocessing import (
    get_predict,
    find_grid,
    get_color,
    get_color_scheme,
    get_mask_from_block_params,
    get_dict_hash,
)
import time
import gc


def initiate_candidates_list(factors, initial_values=None):
    """creating an empty candidates list corresponding to factors
    for each (m,n) factor it is m x n matrix of lists"""
    candidates = []
    if not initial_values:
        initial_values = []
    for n_factor, factor in enumerate(factors):
        candidates.append([])
        for i in range(factor[0]):
            candidates[n_factor].append([])
            for j in range(factor[1]):
                candidates[n_factor][i].append(initial_values.copy())
    return candidates


def filter_candidates(
    target_image,
    factors,
    intersection=0,
    candidates=None,
    original_image=None,
    blocks=None,
    blocks_cache=None,
    max_time=300,
):
    candidates_num = 0
    t_n, t_m = target_image.shape
    if original_image is not None:
        color_scheme = get_color_scheme(original_image)
    new_candidates = initiate_candidates_list(factors)
    start_time = time.time()
    for n_factor, factor in enumerate(factors.copy()):
        for i in range(factor[0]):
            for j in range(factor[1]):
                if blocks is not None:
                    local_candidates = blocks
                else:
                    local_candidates = candidates[n_factor][i][j]

                for data in local_candidates:
                    if time.time() - start_time > max_time:
                        print("stopped")
                        break
                    if blocks is not None:
                        array = data["block"]
                        params = data["params"]
                    else:
                        params = data
                        result, array = get_predict(
                            original_image, data, blocks_cache, color_scheme
                        )
                        if result != 0:
                            continue

                    n, m = array.shape

                    # work with valid candidates only
                    if n <= 0 or m <= 0:
                        continue
                    if (
                        n - intersection != (t_n - intersection) / factor[0]
                        or m - intersection != (t_m - intersection) / factor[1]
                    ):
                        continue

                    start_n = i * (n - intersection)
                    start_m = j * (m - intersection)

                    # checking the sizes of expected and proposed blocks
                    if not (
                        (
                            array.shape[0]
                            == target_image[
                                start_n : start_n + n, start_m : start_m + m
                            ].shape[0]
                        )
                        and (
                            array.shape[1]
                            == target_image[
                                start_n : start_n + n, start_m : j * start_m + m
                            ].shape[1]
                        )
                    ):
                        continue

                    # adding the candidate to the candidates list
                    if (
                        array
                        == target_image[start_n : start_n + n, start_m : start_m + m]
                    ).all():
                        new_candidates[n_factor][i][j].append(params)
                        candidates_num += 1

                # if there is no candidates for one of the cells the whole factor is invalid
                if len(new_candidates[n_factor][i][j]) == 0:
                    factors[n_factor] = [0, 0]
                    break
            if factors[n_factor][0] == 0:
                break
    return factors, new_candidates


def mosaic(sample, rotate_target=0, intersection=0):
    """ combines all possible combinations of blocks into target image"""
    target_image = np.rot90(np.uint8(sample["train"][0]["output"]), rotate_target)
    t_n, t_m = target_image.shape
    factors = []

    if intersection < 0:
        grid_color, grid_size = find_grid(target_image)
        if grid_color < 0:
            return 5, None
        factors = [grid_size]
        grid_color_list = sample["processed_train"][0]["colors"][grid_color]
    else:
        for i in range(1, t_n):
            for j in range(1, t_m):
                if (t_n - intersection) % i == 0 and (t_m - intersection) % j == 0:
                    factors.append([i, j])

    # get the initial candidates
    factors, candidates = filter_candidates(
        target_image,
        factors,
        intersection=intersection,
        candidates=None,
        original_image=None,
        blocks=sample["processed_train"][0]["blocks"],
    )
    gc.collect()

    # filter them, leave only those that ok for all train samples
    for k in range(1, len(sample["train"])):
        if intersection < 0:
            grid_color, grid_size = find_grid(target_image)
            if grid_color < 0:
                return 5, None
            if (factors[0][0] != grid_size[0]) or (factors[0][1] != grid_size[1]):
                return 6, None
            new_grid_color_list = []
            for color_dict in grid_color_list:
                if (
                    get_color(color_dict, sample["processed_train"][k]["colors"])
                    == grid_color
                ):
                    new_grid_color_list.append(color_dict)
            if len(new_grid_color_list) == 0:
                return 7, None
            else:
                grid_color_list = new_grid_color_list.copy()

        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.rot90(np.uint8(sample["train"][k]["output"]), rotate_target)
        if "block_cache" not in sample["processed_train"][k]:
            sample["processed_train"][k]["block_cache"] = {}

        factors, candidates = filter_candidates(
            target_image,
            factors,
            intersection=intersection,
            candidates=candidates,
            original_image=original_image,
            blocks=None,
            blocks_cache=sample["processed_train"][k]["block_cache"],
        )
        del sample["processed_train"][k]["block_cache"]
        gc.collect()

    answers = []
    for _ in sample["test"]:
        answers.append([])
    final_factor_n = -1

    # check if we have at least one valid solution
    for n_factor, factor in enumerate(factors):
        if factor[0] > 0 and factor[1] > 0:
            final_factor_n = n_factor
            factor = factors[final_factor_n]

            for test_n, test_data in enumerate(sample["test"]):
                original_image = np.uint8(test_data["input"])
                color_scheme = get_color_scheme(original_image)
                skip = False
                for i in range(factor[0]):
                    for j in range(factor[1]):
                        result, array = get_predict(
                            original_image,
                            candidates[final_factor_n][i][j][0],
                            color_scheme,
                        )
                        if result != 0:
                            skip = True
                            break
                        n, m = array.shape
                        if i == 0 and j == 0:
                            predict = np.int32(
                                np.zeros(
                                    (
                                        (n - intersection) * factor[0] + intersection,
                                        (m - intersection) * factor[1] + intersection,
                                    )
                                )
                            )
                            if intersection < 0:
                                predict += get_color(
                                    grid_color_list[0], color_scheme["colors"]
                                )

                        predict[
                            i * (n - intersection) : i * (n - intersection) + n,
                            j * (m - intersection) : j * (m - intersection) + m,
                        ] = array
                    if skip:
                        break
                if not skip:
                    answers[test_n].append(np.rot90(predict, k=-rotate_target))

    if final_factor_n == -1:
        return 1, None

    return 0, answers


def mask_to_blocks(sample, rotate_target=0, num_masks=1):
    target_image = np.rot90(np.uint8(sample["train"][0]["output"]), rotate_target)
    t_n, t_m = target_image.shape
    candidates = []
    max_time = 300
    start_time = time.time()
    for block in sample["processed_train"][0]["blocks"]:
        if len(block["params"]) > 0 and block["params"][-1]["type"] == "color_swap":
            continue
        if t_n == block["block"].shape[0] and t_m == block["block"].shape[1]:
            for mask_num, mask in enumerate(sample["processed_train"][0]["masks"]):
                if time.time() - start_time > max_time:
                    break
                if t_n == mask["mask"].shape[0] and t_m == mask["mask"].shape[1]:
                    for color in range(10):
                        if (
                            target_image
                            == block["block"] * (1 - mask["mask"])
                            + mask["mask"] * color
                        ).all():
                            for color_dict in sample["processed_train"][0]["colors"][
                                color
                            ].copy():
                                candidates.append(
                                    {
                                        "block": block["params"],
                                        "mask": {
                                            "params": mask["params"],
                                            "operation": mask["operation"],
                                        },
                                        "color": color_dict.copy(),
                                    }
                                )
    gc.collect()

    for k in range(1, len(sample["train"])):
        start_time = time.time()
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.rot90(np.uint8(sample["train"][k]["output"]), rotate_target)
        t_n, t_m = target_image.shape
        new_candidates = []

        if "block_cache" not in sample["processed_train"][k]:
            sample["processed_train"][k]["block_cache"] = {}
        if "mask_cache" not in sample["processed_train"][k]:
            sample["processed_train"][k]["mask_cache"] = {}

        for candidate in candidates:
            if time.time() - start_time > max_time:
                break
            status, block = get_predict(
                original_image,
                candidate["block"],
                sample["processed_train"][k]["block_cache"],
                color_scheme=sample["processed_train"][k],
            )
            if status != 0 or block.shape[0] != t_n or block.shape[1] != t_m:
                continue
            status, mask = get_mask_from_block_params(
                original_image,
                candidate["mask"],
                block_cache=sample["processed_train"][k]["block_cache"],
                color_scheme=sample["processed_train"][k],
                mask_cache=sample["processed_train"][k]["mask_cache"],
            )
            if status != 0 or mask.shape[0] != t_n or mask.shape[1] != t_m:
                continue
            color = get_color(
                candidate["color"], sample["processed_train"][k]["colors"]
            )
            if color < 0:
                continue
            if (target_image == block * (1 - mask) + mask * color).all():
                new_candidates.append(candidate)
        candidates = new_candidates.copy()
        del sample["processed_train"][k]["mask_cache"]
        del sample["processed_train"][k]["block_cache"]
        gc.collect()

    if len(candidates) == 0:
        return 1, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])

        if "block_cache" not in sample["test"][test_n]:
            sample["processed_train"][test_n]["block_cache"] = {}
        if "mask_cache" not in sample["test"][test_n]:
            sample["processed_train"][test_n]["mask_cache"] = {}

        color_scheme = get_color_scheme(original_image)
        for candidate in candidates:
            status, block = get_predict(
                original_image,
                candidate["block"],
                color_scheme=color_scheme,
                block_cache=sample["processed_train"][test_n]["block_cache"],
            )
            if status != 0:
                continue
            status, mask = get_mask_from_block_params(
                original_image,
                candidate["mask"],
                color_scheme=color_scheme,
                block_cache=sample["processed_train"][test_n]["block_cache"],
                mask_cache=sample["processed_train"][test_n]["mask_cache"],
            )
            if (
                status != 0
                or mask.shape[0] != block.shape[0]
                or mask.shape[1] != block.shape[1]
            ):
                continue
            color = get_color(candidate["color"], color_scheme["colors"])
            if color < 0:
                continue
            prediction = (block * (1 - mask)) + (mask * color)
            answers[test_n].append(np.rot90(prediction, k=-rotate_target))
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 2, None


def paint_mask(sample, rotate_target=0):
    target_image = np.rot90(np.uint8(sample["train"][0]["output"]), rotate_target)
    unique = np.unique(target_image)
    if len(unique) > 2:
        return 3, None
    t_n, t_m = target_image.shape
    candidates = []
    max_time = 300
    start_time = time.time()
    for mask in sample["processed_train"][0]["masks"]:
        if time.time() - start_time > max_time:
            break
        if t_n == mask["mask"].shape[0] and t_m == mask["mask"].shape[1]:
            unique = np.unique(target_image[mask["mask"]])
            if len(unique) != 1:
                continue
            color2 = unique[0]
            unique = np.unique(target_image[np.logical_not(mask["mask"])])
            if len(unique) != 1:
                continue
            color1 = unique[0]
            for color_dict1 in sample["processed_train"][0]["colors"][color1].copy():
                for color_dict2 in sample["processed_train"][0]["colors"][
                    color2
                ].copy():
                    candidates.append(
                        {
                            "mask": {
                                "params": mask["params"],
                                "operation": mask["operation"],
                            },
                            "color1": color_dict1.copy(),
                            "color2": color_dict2.copy(),
                        }
                    )
    gc.collect()

    for k in range(1, len(sample["train"])):
        start_time = time.time()
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.rot90(np.uint8(sample["train"][k]["output"]), rotate_target)
        t_n, t_m = target_image.shape
        new_candidates = []
        if "block_cache" not in sample["processed_train"][k]:
            sample["processed_train"][k]["block_cache"] = {}
        if "mask_cache" not in sample["processed_train"][k]:
            sample["processed_train"][k]["mask_cache"] = {}

        for candidate in candidates:
            if time.time() - start_time > max_time:
                break
            status, mask = get_mask_from_block_params(
                original_image,
                candidate["mask"],
                block_cache=sample["processed_train"][k]["block_cache"],
                color_scheme=sample["processed_train"][k],
                mask_cache=sample["processed_train"][k]["mask_cache"],
            )
            if status != 0 or mask.shape[0] != t_n or mask.shape[1] != t_m:
                continue
            color1 = get_color(
                candidate["color1"], sample["processed_train"][k]["colors"]
            )
            color2 = get_color(
                candidate["color2"], sample["processed_train"][k]["colors"]
            )

            if color1 < 0 or color2 < 0:
                continue

            part1 = (1 - mask) * color1
            part2 = mask * color2
            result = part1 + part2
            result == target_image
            if (target_image == ((1 - mask) * color1 + mask * color2)).all():
                new_candidates.append(candidate)
        candidates = new_candidates.copy()
        del sample["processed_train"][k]["mask_cache"]
        del sample["processed_train"][k]["block_cache"]
        gc.collect()

    if len(candidates) == 0:
        return 1, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        if "block_cache" not in sample["test"][test_n]:
            sample["processed_train"][test_n]["block_cache"] = {}
        if "mask_cache" not in sample["test"][test_n]:
            sample["processed_train"][test_n]["mask_cache"] = {}
        color_scheme = get_color_scheme(original_image)
        for candidate in candidates:
            status, mask = get_mask_from_block_params(
                original_image,
                candidate["mask"],
                color_scheme=color_scheme,
                block_cache=sample["processed_train"][test_n]["block_cache"],
                mask_cache=sample["processed_train"][test_n]["mask_cache"],
            )
            if status != 0:
                continue
            color1 = get_color(candidate["color1"], color_scheme["colors"])
            color2 = get_color(candidate["color2"], color_scheme["colors"])

            if color1 < 0 or color2 < 0:
                continue
            prediction = ((1 - mask) * color1) + (mask * color2)
            answers[test_n].append(np.rot90(prediction, k=-rotate_target))
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 2, None


def generate_corners(
    original_image, simetry_type="rotate", block_size=None, color=None
):
    size = (original_image.shape[0] + 1) // 2, (original_image.shape[1] + 1) // 2
    # corners
    corners = []
    if simetry_type == "rotate":
        corners.append(original_image[: size[0], : size[1]])
        corners.append(np.rot90(original_image[: size[0], -size[1] :], 1))
        corners.append(np.rot90(original_image[-size[0] :, -size[1] :], 2))
        corners.append(np.rot90(original_image[-size[0] :, : size[1]], 3))
    elif simetry_type == "reflect":
        corners.append(original_image[: size[0], : size[1]])
        corners.append(original_image[: size[0], -size[1] :][:, ::-1])
        corners.append(original_image[-size[0] :, -size[1] :][::-1, ::-1])
        corners.append(original_image[-size[0] :, : size[1]][::-1, :])
        if original_image.shape[0] == original_image.shape[1]:
            mask = np.logical_and(original_image != color, original_image.T != color)
            if (original_image.T == original_image)[mask].all():
                corners.append(original_image[: size[0], : size[1]].T)
                corners.append(original_image[: size[0], -size[1] :][:, ::-1].T)
                corners.append(original_image[-size[0] :, -size[1] :][::-1, ::-1].T)
                corners.append(original_image[-size[0] :, : size[1]][::-1, :].T)

    elif simetry_type == "surface":
        for i in range(original_image.shape[0] // block_size[0]):
            for j in range(original_image.shape[1] // block_size[1]):
                corners.append(
                    original_image[
                        i * block_size[0] : (i + 1) * block_size[0],
                        j * block_size[1] : (j + 1) * block_size[1],
                    ]
                )

    return corners


def mosaic_reconstruction_check_corner_consistency(corners, color):
    for i, corner1 in enumerate(corners[:-1]):
        for corner2 in corners[i + 1 :]:
            mask = np.logical_and(corner1 != color, corner2 != color)
            if not (corner1 == corner2)[mask].all():
                return False
    return True


def mosaic_reconstruction_check_corner(
    original_image, target_image, color, simetry_types
):
    if not (original_image == target_image)[original_image != color].all():
        return False

    status, predicted_image = mosaic_reconstruct_corner(
        original_image, color, simetry_types
    )
    if status != 0:
        return False
    temp = (
        predicted_image[: original_image.shape[0], : original_image.shape[1]]
        == target_image
    )
    if (
        predicted_image[: original_image.shape[0], : original_image.shape[1]]
        == target_image
    ).all():
        return True
    return False


def mosaic_reconstruct_corner(original_image, color, simetry_types=None):
    # corners
    target_images = []
    extensions = []
    if simetry_types is None:
        simetry_types = ["rotate", "reflect", "surface"]

    for extensions_sum in range(20):
        for extension0 in range(extensions_sum):
            extension1 = extensions_sum - extension0
            for simetry_type in simetry_types:
                if simetry_type == "rotate" and (
                    original_image.shape[0] + extension0
                    != original_image.shape[1] + extension1
                ):
                    continue
                new_image = np.uint8(
                    np.ones(
                        (
                            original_image.shape[0] + extension0,
                            original_image.shape[1] + extension1,
                        )
                    )
                    * color
                )
                new_image[
                    : original_image.shape[0], : original_image.shape[1]
                ] = original_image

                if simetry_type in ["rotate", "reflect"]:
                    corners = generate_corners(new_image, simetry_type, color=color)
                    if not mosaic_reconstruction_check_corner_consistency(
                        corners, color
                    ):
                        continue
                elif simetry_type == "surface":
                    sizes_found = False
                    for block_sizes_sum in range(
                        2, min(15, new_image.shape[0] + new_image.shape[0] - 2)
                    ):
                        for block_size1 in range(
                            1, min(block_sizes_sum - 1, new_image.shape[0] - 1)
                        ):
                            if new_image.shape[0] % block_size1 != 0:
                                continue
                            block_size2 = min(
                                block_sizes_sum - block_size1, new_image.shape[1] - 1
                            )
                            if new_image.shape[1] % block_size2 != 0:
                                continue
                            corners = generate_corners(
                                new_image, simetry_type, (block_size1, block_size2)
                            )
                            if not mosaic_reconstruction_check_corner_consistency(
                                corners, color
                            ):
                                continue
                            else:
                                sizes_found = True
                                break
                        if sizes_found:
                            break
                    if not sizes_found:
                        continue

                final_corner = corners[0].copy()
                for i, corner in enumerate(corners[1:]):
                    mask = np.logical_and(final_corner == color, corner != color)
                    final_corner[mask] = corner[mask]
                if (final_corner == color).any() and final_corner.shape[
                    0
                ] == final_corner.shape[1]:
                    mask = final_corner == color
                    final_corner[mask] = final_corner.T[mask]

                size = final_corner.shape
                target_image = new_image.copy()
                target_image[: size[0], : size[1]] = final_corner
                if simetry_type == "rotate":
                    target_image[: size[0], -size[1] :] = np.rot90(final_corner, -1)
                    target_image[-size[0] :, -size[1] :] = np.rot90(final_corner, -2)
                    target_image[-size[0] :, : size[1]] = np.rot90(final_corner, -3)
                elif simetry_type == "reflect":
                    target_image[: size[0], -size[1] :] = final_corner[:, ::-1]
                    target_image[-size[0] :, -size[1] :] = final_corner[::-1, ::-1]
                    target_image[-size[0] :, : size[1]] = final_corner[::-1, :]
                elif simetry_type == "surface":
                    for i in range(new_image.shape[0] // size[0]):
                        for j in range(new_image.shape[1] // size[1]):
                            target_image[
                                i * size[0] : (i + 1) * size[0],
                                j * size[1] : (j + 1) * size[1],
                            ] = final_corner

                target_image = target_image[
                    : original_image.shape[0], : original_image.shape[1]
                ]
                extensions.append(extension0 + extension1)
                return 0, target_image

    return 1, None


def filter_list_of_dicts(list1, list2):
    final_list = []
    for item1 in list1:
        for item2 in list2:
            if get_dict_hash(item1) == get_dict_hash(item2):
                final_list.append(item1)
    return final_list


def reflect_rotate_roll(
    image, reflect=(False, False), rotate=0, inverse=False, roll=(0, 0)
):
    if inverse:
        result = np.rot90(image, -rotate).copy()
    else:
        result = np.rot90(image, rotate).copy()
    if reflect[0]:
        result = result[::-1]
    if reflect[1]:
        result = result[:, ::-1]
    if inverse:
        result = np.roll(result, -roll[0], axis=0)
        result = np.roll(result, -roll[1], axis=1)
    else:
        result = np.roll(result, roll[0], axis=0)
        result = np.roll(result, roll[1], axis=1)

    return result


def mosaic_reconstruction(
    sample,
    rotate=0,
    simetry_types=None,
    reflect=(False, False),
    rotate_target=0,
    roll=(0, 0),
):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        original_image = np.rot90(np.uint8(sample["train"][k]["input"]), rotate)
        target_image = np.rot90(np.uint8(sample["train"][k]["output"]), rotate)
        target_image = reflect_rotate_roll(
            target_image,
            reflect=reflect,
            rotate=rotate_target,
            roll=roll,
            inverse=False,
        )
        if original_image.shape != target_image.shape:
            return 1, None
        for color_num in range(10):
            if mosaic_reconstruction_check_corner(
                original_image, target_image, color_num, simetry_types
            ):
                for color_dict in sample["processed_train"][k]["colors"][color_num]:
                    color_candidates.append(color_dict)
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            color = get_color(color_dict, color_scheme["colors"])
            status, prediction = mosaic_reconstruct_corner(
                np.rot90(original_image, rotate), color, simetry_types
            )
            if status != 0:
                continue
            prediction = reflect_rotate_roll(
                prediction,
                reflect=reflect,
                rotate=rotate_target,
                roll=roll,
                inverse=True,
            )
            answers[test_n].append(np.rot90(prediction, -rotate))
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


## one color case


def one_color(sample):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        target_image = np.uint8(sample["train"][k]["output"])
        if target_image.shape[0] != 1 or target_image.shape[1] != 1:
            return 1, None

        for color_dict in sample["processed_train"][k]["colors"][target_image[0, 0]]:
            color_candidates.append(color_dict)
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            color = get_color(color_dict, color_scheme["colors"])
            prediction = np.array([[color]])
            answers[test_n].append(prediction)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def several_colors_square(sample):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        target_image = np.uint8(sample["train"][k]["output"])
        if target_image.shape[0] != target_image.shape[1]:
            return 1, None
        size = target_image.shape[0]
        if size > sample["processed_train"][k]["colors_num"]:
            return 2, None

        size_diff = sample["processed_train"][k]["colors_num"] - size
        for i in range(size_diff + 1):
            colors_array = np.zeros((size, size))
            for j in range(size):
                colors_array[j:-j] = sample["processed_train"][k]["colors_sorted"][
                    i + j
                ]
            if (colors_array == target_image).all():
                color_candidates.append(
                    {"type": "square", "i": i, "direct": 0, "size_diff": size_diff}
                )

            for j in range(size):
                colors_array[j:-j] = sample["processed_train"][k]["colors_sorted"][
                    ::-1
                ][i + j]
            if (colors_array == target_image).all():
                color_candidates.append(
                    {"type": "square", "i": i, "direct": 1, "size_diff": size_diff}
                )

        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for result_dict in color_candidates_final:
            i = result_dict["i"]
            rotate = result_dict["rotate"]
            size = color_scheme["colors_num"] - size_diff
            prediction = np.zeros((size, size))
            for j in range(size):
                if result_dict["direct"] == 0:
                    prediction[j:-j] = sample["processed_train"][k]["colors_sorted"][
                        i + j
                    ]
                else:
                    prediction[j:-j] = sample["processed_train"][k]["colors_sorted"][
                        ::-1
                    ][i + j]

            answers[test_n].append(prediction)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def several_colors(sample):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        target_image = np.uint8(sample["train"][k]["output"])
        if target_image.shape[0] != 1 and target_image.shape[1] != 1:
            return 1, None
        size = target_image.shape[0] * target_image.shape[1]
        if size > sample["processed_train"][k]["colors_num"]:
            return 2, None

        size_diff = sample["processed_train"][k]["colors_num"] - size
        for i in range(size_diff + 1):
            for rotate in range(4):
                colors_array = np.rot90(
                    np.array(
                        [sample["processed_train"][k]["colors_sorted"][i : i + size]]
                    ),
                    rotate,
                )
                if (colors_array.shape == target_image.shape) and (
                    colors_array == target_image
                ).all():
                    color_candidates.append(
                        {
                            "type": "linear",
                            "i": i,
                            "rotate": rotate,
                            "size_diff": size_diff,
                        }
                    )

        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for result_dict in color_candidates_final:
            i = result_dict["i"]
            rotate = result_dict["rotate"]
            size = color_scheme["colors_num"] - size_diff
            prediction = np.rot90(
                np.array([color_scheme["colors_sorted"][i : i + size]]), rotate
            )
            answers[test_n].append(prediction)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def extract_mosaic_block(
    sample,
    rotate=0,
    simetry_types=None,
    reflect=(False, False),
    rotate_target=0,
    roll=(0, 0),
):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        original_image = np.rot90(np.uint8(sample["train"][k]["input"]), rotate)
        target_image = np.rot90(np.uint8(sample["train"][k]["output"]), rotate)
        target_image = reflect_rotate_roll(
            target_image,
            reflect=reflect,
            rotate=rotate_target,
            roll=roll,
            inverse=False,
        )
        for color_num in range(10):
            mask = original_image == color_num
            sum0 = mask.sum(0)
            sum1 = mask.sum(1)

            if len(np.unique(sum0)) != 2 or len(np.unique(sum1)) != 2:
                continue
            if target_image.shape[0] != max(sum0) or target_image.shape[1] != max(sum1):
                continue

            indices0 = np.arange(len(sum1))[sum1 > 0]
            indices1 = np.arange(len(sum0))[sum0 > 0]

            generated_target_image = original_image.copy()
            generated_target_image[
                indices0.min() : indices0.max() + 1, indices1.min() : indices1.max() + 1
            ] = target_image

            if mosaic_reconstruction_check_corner(
                original_image, generated_target_image, color_num, simetry_types
            ):
                for color_dict in sample["processed_train"][k]["colors"][color_num]:
                    color_candidates.append(color_dict)
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.rot90(np.uint8(test_data["input"]), rotate)
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            color = get_color(color_dict, color_scheme["colors"])
            status, prediction = mosaic_reconstruct_corner(
                original_image, color, simetry_types
            )

            if status != 0:
                continue
            prediction = reflect_rotate_roll(
                prediction,
                reflect=reflect,
                rotate=rotate_target,
                roll=roll,
                inverse=True,
            )
            mask = original_image == color
            sum0 = mask.sum(0)
            sum1 = mask.sum(1)
            indices0 = np.arange(len(sum1))[sum1 > 0]
            indices1 = np.arange(len(sum0))[sum0 > 0]

            prediction = prediction[
                indices0.min() : indices0.max() + 1, indices1.min() : indices1.max() + 1
            ]

            answers[test_n].append(np.rot90(prediction, -rotate))
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def apply_pattern(mask, pattern, backgroud_color=0, inverse=False):
    size = (mask.shape[0] * pattern.shape[0], mask.shape[1] * pattern.shape[1])
    result = np.ones(size) * backgroud_color
    for i in range(mask.shape[0]):
        for j in range(mask.shape[1]):
            if mask[i, j] != inverse:
                result[
                    i * pattern.shape[0] : (i + 1) * pattern.shape[0],
                    j * pattern.shape[1] : (j + 1) * pattern.shape[1],
                ] = pattern

    return result


def swap_two_colors(image):
    unique = np.unique(image)
    if len(unique) != 2:
        return 1, None
    result = image.copy()
    result[image == unique[0]] = unique[1]
    result[image == unique[1]] = unique[0]
    return 0, result


def self_pattern(sample):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.uint8(sample["train"][k]["output"])
        if (
            target_image.shape[0] != original_image.shape[0] ** 2
            or target_image.shape[0] != original_image.shape[1] ** 2
        ):
            return 1, None
        for color_mask in range(10):
            if not (original_image == color_mask).any():
                continue
            for background_color in range(10):
                if not (target_image == background_color).any():
                    continue
                for inverse in [True, False]:
                    for swap in [True, False]:
                        if swap:
                            status, new_image = swap_two_colors(original_image)
                            if status != 0:
                                new_image = original_image
                        else:
                            new_image = original_image
                        predict = apply_pattern(
                            new_image == color_mask,
                            new_image,
                            background_color,
                            inverse,
                        )
                        if (predict == target_image).all():
                            for color_mask_dict in sample["processed_train"][k][
                                "colors"
                            ][color_mask]:
                                for color_background_dict in sample["processed_train"][
                                    k
                                ]["colors"][background_color]:
                                    color_candidates.append(
                                        {
                                            "color_mask": color_mask_dict,
                                            "background_color": color_background_dict,
                                            "inverse": inverse,
                                            "swap": swap,
                                        }
                                    )
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            color_mask = get_color(color_dict["color_mask"], color_scheme["colors"])
            background_color = get_color(
                color_dict["background_color"], color_scheme["colors"]
            )
            if color_dict["swap"]:
                status, new_image = swap_two_colors(original_image)
                if status != 0:
                    new_image = original_image
            else:
                new_image = original_image
            prediction = apply_pattern(
                new_image == color_mask,
                new_image,
                background_color,
                color_dict["inverse"],
            )
            answers[test_n].append(prediction)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def combine_two_lists(list1, list2):
    result = list1.copy()
    for item2 in list2:
        exist = False
        for item1 in list1:
            if (item2 == item1).all():
                exist = True
                break
        if not exist:
            result.append(item2)
    return result


def intersect_two_lists(list1, list2):
    result = []
    for item2 in list2:
        for item1 in list1:
            if (item2.shape == item1.shape) and (item2 == item1).all():
                result.append(item2)
                break
    return result


def get_patterns(original_image, target_image):
    pattern_list = []
    if target_image.shape[0] % original_image.shape[0] != 0:
        return []
    if target_image.shape[1] % original_image.shape[1] != 0:
        return []

    size = (
        target_image.shape[0] // original_image.shape[0],
        target_image.shape[1] // original_image.shape[1],
    )
    if max(size) == 1:
        return []
    for i in range(original_image.shape[0]):
        for j in range(original_image.shape[1]):
            current_block = target_image[
                i * size[0] : (i + 1) * size[0], j * size[1] : (j + 1) * size[1]
            ]
            pattern_list = combine_two_lists(pattern_list, [current_block])

    return pattern_list


def fixed_pattern(sample):
    color_candidates_final = []
    total_patterns = []

    for k in range(len(sample["train"])):
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.uint8(sample["train"][k]["output"])
        patterns = get_patterns(original_image, target_image)
        if k == 0:
            total_patterns = patterns
        else:
            total_patterns = intersect_two_lists(total_patterns, patterns)
        if len(total_patterns) == 0:
            return 1, None

    for k in range(len(sample["train"])):
        color_candidates = []
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.uint8(sample["train"][k]["output"])
        for pattern_num, pattern in enumerate(total_patterns):
            for color_mask in range(10):
                if not (original_image == color_mask).any():
                    continue
                for background_color in range(10):
                    if not (target_image == background_color).any():
                        continue
                    for inverse in [True, False]:
                        for swap in [True, False]:
                            if swap:
                                status, new_image = swap_two_colors(original_image)
                                if status != 0:
                                    new_image = original_image
                            else:
                                new_image = original_image
                            predict = apply_pattern(
                                new_image == color_mask,
                                pattern,
                                background_color,
                                inverse,
                            )
                            if (predict == target_image).all():
                                for color_mask_dict in sample["processed_train"][k][
                                    "colors"
                                ][color_mask]:
                                    for color_background_dict in sample[
                                        "processed_train"
                                    ][k]["colors"][background_color]:
                                        color_candidates.append(
                                            {
                                                "color_mask": color_mask_dict,
                                                "background_color": color_background_dict,
                                                "inverse": inverse,
                                                "swap": swap,
                                                "pattern": pattern_num,
                                            }
                                        )
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            color_mask = get_color(color_dict["color_mask"], color_scheme["colors"])
            background_color = get_color(
                color_dict["background_color"], color_scheme["colors"]
            )
            if color_dict["swap"]:
                status, new_image = swap_two_colors(original_image)
                if status != 0:
                    new_image = original_image
            else:
                new_image = original_image
            prediction = apply_pattern(
                new_image == color_mask,
                total_patterns[color_dict["pattern"]],
                background_color,
                color_dict["inverse"],
            )
            answers[test_n].append(prediction)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def fill_image(image, background_color, fill_color):
    result = image.copy()
    for i in range(1, image.shape[0] - 1):
        for j in range(1, image.shape[1] - 1):
            if (
                image[i - 1 : i + 2, j - 1 : j + 2][
                    np.array(
                        [[True, True, True], [True, False, True], [True, True, True]]
                    )
                ]
                == background_color
            ).all():
                result[i, j] = fill_color
    return result


def fill_inner(sample):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.uint8(sample["train"][k]["output"])
        if original_image.shape != target_image.shape:
            return 1, None
        for background_color in range(10):
            if not (original_image == background_color).any():
                continue
            for fill_color in range(10):
                if not (target_image == fill_color).any():
                    continue
                if not (target_image == original_image)[
                    np.logical_and(
                        target_image != background_color, target_image != fill_color
                    )
                ].all():
                    continue
                predict = fill_image(original_image, background_color, fill_color)
                if (predict == target_image).all():
                    for color_fill_dict in sample["processed_train"][k]["colors"][
                        fill_color
                    ]:
                        for color_background_dict in sample["processed_train"][k][
                            "colors"
                        ][background_color]:
                            color_candidates.append(
                                {
                                    "fill_color": color_fill_dict,
                                    "background_color": color_background_dict,
                                }
                            )
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            fill_color = get_color(color_dict["fill_color"], color_scheme["colors"])
            background_color = get_color(
                color_dict["background_color"], color_scheme["colors"]
            )

            predict = fill_image(original_image, background_color, fill_color)
            answers[test_n].append(predict)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None


def fill_outer_image(image, background_color, fill_color):
    result = image.copy()
    for i in range(1, image.shape[0] - 1):
        for j in range(1, image.shape[1] - 1):
            if image[i, j] == fill_color:
                result[i - 1 : i + 2, j - 1 : j + 2][
                    np.array(
                        [[True, True, True], [True, False, True], [True, True, True]]
                    )
                ] = background_color

    return result


def fill_outer(sample):
    color_candidates_final = []

    for k in range(len(sample["train"])):
        color_candidates = []
        original_image = np.uint8(sample["train"][k]["input"])
        target_image = np.uint8(sample["train"][k]["output"])
        if original_image.shape != target_image.shape:
            return 1, None
        for background_color in range(10):
            if not (target_image == background_color).any():
                continue
            for fill_color in range(10):
                if not (target_image == fill_color).any():
                    continue
                if not (target_image == original_image)[
                    np.logical_and(
                        target_image != background_color, target_image != fill_color
                    )
                ].all():
                    continue
                predict = fill_outer_image(original_image, background_color, fill_color)
                if (predict == target_image).all():
                    for color_fill_dict in sample["processed_train"][k]["colors"][
                        fill_color
                    ]:
                        for color_background_dict in sample["processed_train"][k][
                            "colors"
                        ][background_color]:
                            color_candidates.append(
                                {
                                    "fill_color": color_fill_dict,
                                    "background_color": color_background_dict,
                                }
                            )
        if k == 0:
            color_candidates_final = color_candidates
        else:
            color_candidates_final = filter_list_of_dicts(
                color_candidates, color_candidates_final
            )
        if len(color_candidates_final) == 0:
            return 2, None

    answers = []
    for _ in sample["test"]:
        answers.append([])

    result_generated = False
    for test_n, test_data in enumerate(sample["test"]):
        original_image = np.uint8(test_data["input"])
        color_scheme = get_color_scheme(original_image)
        for color_dict in color_candidates_final:
            fill_color = get_color(color_dict["fill_color"], color_scheme["colors"])
            background_color = get_color(
                color_dict["background_color"], color_scheme["colors"]
            )

            predict = fill_outer_image(original_image, background_color, fill_color)
            answers[test_n].append(predict)
            result_generated = True

    if result_generated:
        return 0, answers
    else:
        return 3, None
