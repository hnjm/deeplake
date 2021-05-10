import os
import numpy as np
import pickle

from typing import Any, Callable, List, Tuple

from hub.core.chunk_engine import generate_chunks

from .meta import (
    has_meta,
    get_meta,
    set_meta,
    default_meta,
    validate_and_update_meta,
)
from .index_map import has_index_map, get_index_map, set_index_map, default_index_map
from .util import array_to_bytes, index_map_entry_to_bytes, normalize_and_batchify_shape


def chunk_and_write_array(
    array: np.ndarray,
    key: str,
    compression,
    chunk_size: int,
    storage,
    batched: bool = False,
):

    array = normalize_and_batchify_shape(array, batched=batched)
    meta = validate_and_update_meta(
        key,
        storage,
        **{
            "compression": compression.__name__,
            "chunk_size": chunk_size,
            "dtype": array.dtype.name,
            "length": array.shape[0],
        },
    )
    index_map = get_index_map(key, storage)


def _OLD_chunk_and_write_array(
    array: np.ndarray,
    key: str,
    compression,
    chunk_size: int,
    storage,
    batched: bool = False,
):
    """
    Chunk, & write array to `storage`.
    """

    # TODO: for most efficiency, we should try to use `batched` as often as possible.

    # TODO: validate array shape (no 0s in shape)
    array = normalize_and_batchify_shape(array, batched=batched)

    # validate & update meta
    _meta = {
        "compression": compression.__name__,
        "chunk_size": chunk_size,
        "dtype": array.dtype.name,
    }
    validate_meta_is_compatible(key, storage, **_meta)
    meta = update_meta(
        key,
        storage,
        length=array.shape[0],
        **_meta,
    )

    local_chunk_index = 0

    # TODO: move into function:
    if has_index_map(key, storage):
        index_map = get_index_map(key, storage)
    else:
        index_map = default_index_map()

    for i in range(array.shape[0]):
        sample = array[i]
        if compression.subject == "sample":
            # do sample-wise compression
            sample = compression.compress(sample)

        # TODO: this can be replaced with hilbert curve or something
        b = array_to_bytes(sample)

        """chunk & write bytes"""
        # bytes left in last chunk
        bllc = 0
        start_byte = 0
        im_len = len(index_map)
        last_chunk = None
        if im_len > 0:
            last_index_entry = index_map[-1]
            last_incomplete_chunk_names = last_index_entry["incomplete_chunk_names"]

            if last_incomplete_chunk_names == 1:
                last_chunk_index = im_len - 1
                last_chunk = last_chunk_key = os.path.join(
                    key, "c%i" % last_chunk_index
                )
                # `bllc` can't be negative, covered by `validate_meta_is_compatible`
                bllc = chunk_size - len(last_chunk)
                start_byte = len(last_chunk)

            elif len(last_incomplete_chunk_names) > 1:
                # TODO: exceptions.py
                raise Exception(
                    "There shouldn't be more than 1 incomplete chunk per sample."
                )

        chunk_gen = generate_chunks(b, chunk_size, bytes_left_in_last_chunk=bllc)
        chunk_names = []
        incomplete_chunk_names = []
        end_byte = None

        for chunk in chunk_gen:
            # TODO: chunk_name should be based on `global_chunk_index`
            chunk_name = "c%i" % local_chunk_index

            end_byte = len(chunk)  # end byte is based on the uncompressed chunk

            if compression.subject == "chunk":
                # TODO: add threshold for compressing (in case user specifies like 10gb chunk_size)

                if len(chunk) >= chunk_size:
                    # only compress if it is a full chunk
                    chunk = compression.compress(chunk)
                else:
                    incomplete_chunk_names.append(chunk_name)

                # TODO: make this more efficient
                if last_chunk is not None:
                    last_chunk = bytearray(last_chunk)
                    last_chunk.extend(chunk[:bllc])
                    last_chunk = None
                    storage[last_chunk_index] = bytes(last_chunk)

            chunk_names.append(chunk_name)
            chunk_key = os.path.join(key, chunk_name)
            storage[chunk_key] = chunk

            local_chunk_index += 1

        """"""

        # TODO: make note of incomplete chunks
        # for chunk_name in incomplete_chunk_names:
        # storage[os

        # TODO: keep track of `sample.shape` over time & add the max_shape:min_shape interval into meta.json for easy queries

        # TODO: encode index_map_entry as array instead of dictionary
        index_map_entry = {
            "chunk_names": chunk_names,
            "incomplete_chunk_names": incomplete_chunk_names,
            "start_byte": start_byte,
            "end_byte": end_byte,
            "shape": sample.shape,  # shape per sample for dynamic tensors (if strictly fixed-size, store this in meta)
        }
        index_map.append(index_map_entry)

    # TODO: chunk index_map
    set_index_map(key, storage, index_map)

    # update meta after everything is done
    set_meta(key, storage, meta)
