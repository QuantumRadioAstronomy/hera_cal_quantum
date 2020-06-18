#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-
# Copyright 2019 the HERA Project
# Licensed under the MIT License
"""
Script for generating text files containing baseline list strings.
Each text file lists the baselines to be processed in each
compute job in baseline parallelization mode.
"""
from hera_cal import io

parser = io.antpairpol_parallization_parser()

io.generate_antpairpol_parallelization_files(filename=a.template_file, writedir=a.directory,
                                             bls_per_chunk=a.bls_per_chunk,
                                             polarizations=a.polarizations)
