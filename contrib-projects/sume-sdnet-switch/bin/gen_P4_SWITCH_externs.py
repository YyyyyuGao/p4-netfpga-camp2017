#!/usr/bin/env python

#
# Copyright (c) 2017 Stephen Ibanez
# All rights reserved.
#
# This software was developed by Stanford University and the University of Cambridge Computer Laboratory 
# under National Science Foundation under Grant No. CNS-0855268,
# the University of Cambridge Computer Laboratory under EPSRC INTERNET Project EP/H040536/1 and
# by the University of Cambridge Computer Laboratory under DARPA/AFRL contract FA8750-11-C-0249 ("MRC2"), 
# as part of the DARPA MRC research programme.
#
# @NETFPGA_LICENSE_HEADER_START@
#
# Licensed to NetFPGA C.I.C. (NetFPGA) under one or more contributor
# license agreements.  See the NOTICE file distributed with this work for
# additional information regarding copyright ownership.  NetFPGA licenses this
# file to you under the NetFPGA Hardware-Software License, Version 1.0 (the
# "License"); you may not use this file except in compliance with the
# License.  You may obtain a copy of the License at:
#
#   http://www.netfpga-cic.org
#
# Unless required by applicable law or agreed to in writing, Work distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations under the License.
#
# @NETFPGA_LICENSE_HEADER_END@
#

import sys, os, argparse, re, json
from collections import OrderedDict
from extern_data import *

CPU_REGS_TEMPLATE = "externs/cpu_regs_template.v"
CPU_REGS_DEFINES_TEMPLATE = "externs/cpu_regs_defines_template.v"

EXTERN_DEFINES_FILE = "{0}_extern_defines.json"
CLI_dir = "CLI"

p4_externs = OrderedDict()

"""
Read the switch_info_file to get the user engine information
"""
def find_p4_externs(switch_info_file):
    with open(switch_info_file) as f:
        switch_info = json.load(f)
    user_engines = switch_info['user_engines']
    for engine in user_engines:
        for sig in extern_data.keys():
            if sig in engine['p4_name']:
                px_name = engine['px_name']
                p4_externs[px_name] = engine
                p4_externs[px_name]['extern_type'] = sig
                p4_externs[px_name]['prefix_name'] = engine['p4_name'].replace('_'+sig, '')

def get_extern_control_width(P4_SWITCH_dir):
    global p4_externs
    for extern_name, extern_dict in p4_externs.items():
        extern_dir = find_extern_dir(extern_name, P4_SWITCH_dir)

        template_file = None
        for (dirpath, dirnames, filenames) in os.walk(extern_dir):
            for filename in filenames:
                if (re.match(r".*{}_.*\.v\.stub".format(extern_name), filename)):
                    template_file = os.path.join(extern_dir, filename)

        try:
            content = open(template_file).read()
        except:
            print >> sys.stderr, "ERROR: Could not read template file for extern {}".format(extern_name)
            sys.exit(1)

        # extract address width
        searchObj = re.search(r"input(.*)control_S_AXI_AWADDR", content)
        if(searchObj is not None and ':' in searchObj.group(1)):
            addr_bits = searchObj.group(1).replace('[','').replace(']','')
            addr_bits = map(int, addr_bits.split(':'))
            extern_dict['control_width'] = addr_bits[0] - addr_bits[1] + 1
        elif searchObj is not None:
            extern_dict['control_width'] = 1
        else:
            extern_dict['control_width'] = 0
 
"""
Read P4_SWITCH.h to determine the offset address and compute the base address
"""
def get_extern_address(P4_SWITCH_dir, P4_SWITCH, P4_SWITCH_base_addr):
    global p4_externs
    try:
        contents = open(os.path.join(P4_SWITCH_dir, P4_SWITCH + '.h')).read()
    except IOError as e:
        print >> sys.stderr, "ERROR: could not open {} to get extern address offsets".format(P4_SWITCH + '.h')
        sys.exit(1)
    for extern_name, extern_dict in p4_externs.items():
        if ('control_width' in extern_dict.keys() and extern_dict['control_width'] > 0):
            extern_type = extern_dict['extern_type']
            address_format = r"#define  {}__{}__START_ADDRESS\s*([\dxabcdefABCDEF]*)".format(P4_SWITCH, extern_name)
            searchObj = re.search(address_format, contents)
            try:
                assert(searchObj is not None)
            except:
                print >> sys.stderr, "ERROR: cannot find address for {0} in {1}".format(extern_name, P4_SWITCH + '.h')
                sys.exit(1)
            addr_offset = int(searchObj.group(1), 0)
            extern_dict['addr_offset'] = addr_offset
            extern_dict['base_addr'] = P4_SWITCH_base_addr + addr_offset

"""
Find the UserEngine directory corresponding to extern_name
"""
def find_extern_dir(extern_name, P4_SWITCH_dir):
    # look for extern directories
    for (dirpath, dirnames, filenames) in os.walk(P4_SWITCH_dir):
        for dirname in dirnames:
            matchObj = re.match(r"^{}.*\.HDL".format(extern_name), dirname)
            if matchObj:
                return os.path.join(P4_SWITCH_dir, dirname)
    print >> sys.stderr, "WARNING: could not find directory corresponding to extern: {}".format(extern_name)


def get_field_width(field_name, tuple_list):
    for dic in tuple_list:
        if dic['px_name'] == field_name:
            return dic['msb'] - dic['lsb'] + 1
    print >> sys.stderr, "WARNING: could not find bit width for field {}".format(field_name)
    return None

def run_replace_cmd(contents, pattern, cmd, extern_dict):
    searchObj = re.search(r"input_width\((.*)\)", cmd)
    if searchObj is not None:
        field_name = searchObj.group(1)
        width = get_field_width(field_name, extern_dict['input_tuple'])
        return contents.replace(pattern, str(width))
    
    searchObj = re.search(r"output_width\((.*)\)", cmd)
    if searchObj is not None:
        field_name = searchObj.group(1)
        width = get_field_width(field_name, extern_dict['output_tuple'])
        return contents.replace(pattern, str(width))
    elif (cmd == 'extern_name'):
        return contents.replace(pattern, extern_dict['px_name'])
    elif (cmd == 'module_name'):
        return contents.replace(pattern, extern_dict['module_name'])
    elif (cmd == 'prefix_name'):
        return contents.replace(pattern, extern_dict['prefix_name'])
    elif (cmd == 'addr_width'):
        return contents.replace(pattern, str(extern_dict['control_width'])) #TODO: replace with whatever keyword is used for this annotation
#    elif (cmd == 'max_cycles'):
#        return contents.replace(pattern, str(extern_dict['max_cycles'])) #TODO: replace with whatever keyword is used for this annotation
    else:
        print >> sys.stderr, "WARNING: could not replace {} using command {} for extern {}".format(pattern, cmd, extern_dict['p4_name'])
        return contents

"""
Create the *_cpu_regs.v and *_cpu_regs_defines.v files for externs that have a control interface
"""
def write_cpu_regs_module(templates_dir, extern_dir, extern_dict):
    try:
        cpu_regs_template = open(os.path.join(templates_dir, CPU_REGS_TEMPLATE)).read()
        cpu_regs_defines_template = open(os.path.join(templates_dir, CPU_REGS_DEFINES_TEMPLATE)).read()
    except IOError as e:
        print >> sys.stderr, "ERROR: could not read cpu_regs template files"
        sys.exit(1)
    
    extern_type = extern_dict['extern_type']
    newModule = cpu_regs_template
    newDefines = cpu_regs_defines_template
    for pattern, cmd in extern_data[extern_type]['replacements'].items(): 
        newModule = run_replace_cmd(newModule, pattern, cmd, extern_dict)
        newDefines = run_replace_cmd(newDefines, pattern, cmd, extern_dict)

    # write new cpu_regs file
    cpu_regs_file = '{}_cpu_regs.v'.format(extern_dict['prefix_name'])
    with open(os.path.join(extern_dir, cpu_regs_file), 'w') as f:
        f.write(newModule)

    # write new cpu_regs_defines file
    cpu_regs_defines_file = '{}_cpu_regs_defines.v'.format(extern_dict['prefix_name'])
    with open(os.path.join(extern_dir, cpu_regs_defines_file), 'w') as f:
        f.write(newDefines)

"""
Creates the extern modules from the templates
"""
def make_extern_modules(templates_dir, P4_SWITCH_dir):
    global p4_externs
    for extern_name, extern_dict in p4_externs.items():
        extern_type = extern_dict['extern_type']
        template_file = extern_data[extern_type]['template_file']
        try:
            extern_template = open(os.path.join(templates_dir, template_file)).read()
        except IOError as e:
            print >> sys.stderr, "ERROR: Could not open template file for extern: {}".format(extern_name)
            sys.exit(1)
        extern_dir = find_extern_dir(extern_name, P4_SWITCH_dir)
        module_name = os.path.basename(os.path.normpath(extern_dir)).replace(".HDL", "") 
        extern_dict['module_name'] = module_name
        file_name = module_name + ".v"
        for pattern, cmd in extern_data[extern_type]['replacements'].items():
            extern_template = run_replace_cmd(extern_template, pattern, cmd, extern_dict)
        # write extern module
        with open(os.path.join(extern_dir, file_name), 'w') as f:
            f.write(extern_template)

        # write cpu_regs module if the extern has a control interface
        if ('control_width' in extern_dict.keys() and extern_dict['control_width'] > 0):
            write_cpu_regs_module(templates_dir, extern_dir, extern_dict)


"""
Write all extern info into EXTERN_DEFINES json file
"""
def dump_extern_defines(P4_SWITCH_dir, testdata_dir, sw_dir, P4_SWITCH_base_addr, P4_SWITCH):
    global p4_externs

    extern_defines = OrderedDict()
    for extern_name, extern_dict in p4_externs.items():
        extern_defines[extern_dict['prefix_name']] = extern_dict 

    # dump to testdata directory
    with open(os.path.join(testdata_dir, EXTERN_DEFINES_FILE.format(P4_SWITCH)), 'w') as f:
        json.dump(extern_defines, f)

    # dump to CLI directory
    cli_dir = os.path.join(sw_dir, CLI_dir)
    if not os.path.exists(cli_dir):
        os.makedirs(cli_dir)
    with open(os.path.join(cli_dir, EXTERN_DEFINES_FILE.format(P4_SWITCH)), 'w') as f:
        json.dump(extern_defines, f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('switch_info_file', type=str, help="the switch info file")
    parser.add_argument('P4_SWITCH_dir', type=str, help="the config_writes.txt file")
    parser.add_argument('templates_dir', type=str, help="the base address of the P4_SWITCH")
    parser.add_argument('testdata_dir', type=str, help="the testdata directory to put the P4_SWITCH_reg_defines.py file")
    parser.add_argument('sw_dir', type=str, help="the software directory that will contain the auto generated API folder")
    parser.add_argument('--base_address', type=str, default="0x44020000", help="the base address of the P4_SWITCH module")
    args = parser.parse_args()

    P4_SWITCH = os.path.basename(os.path.normpath(args.P4_SWITCH_dir))

    find_p4_externs(args.switch_info_file)
    get_extern_control_width(args.P4_SWITCH_dir)
    get_extern_address(args.P4_SWITCH_dir, P4_SWITCH, int(args.base_address,0))
    make_extern_modules(args.templates_dir, args.P4_SWITCH_dir)

    dump_extern_defines(args.P4_SWITCH_dir, args.testdata_dir, args.sw_dir, int(args.base_address,0), P4_SWITCH) 


if __name__ == "__main__":
    main()


