#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Author  : Charles Lai
@Contact : qqing_lai@hotmail.com
@Time    : 2020/5/14 下午4:31
@FileName: custom_format.py
@Blog    : https://blog.imaojia.com
"""

import xml.etree.ElementTree as ET
import xmltodict


def convert_xml_to_str_with_pipeline(xml, url, secret, desc, jenkinsfile, scm=True):
    """
    scm
    True: jenkinsfile为指定的git地址
    False: jenkinsfile为具体的pipeline
    """
    xml_dict = xmltodict.parse(xml)
    if scm:
        xml_dict['flow-definition']['definition']['@class'] = 'org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition'
        xml_dict['flow-definition']['definition']['scm']['userRemoteConfigs']['hudson.plugins.git.UserRemoteConfig'][
            'url'] = url
        xml_dict['flow-definition']['definition']['scm']['userRemoteConfigs']['hudson.plugins.git.UserRemoteConfig'][
            'credentialsId'] = secret
        xml_dict['flow-definition']['definition']['scriptPath'] = jenkinsfile
    else:
        xml_dict['flow-definition']['definition']['@class'] = 'org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition'
        xml_dict['flow-definition']['definition']['script'] = jenkinsfile
        xml_dict['flow-definition']['definition']['sandbox'] = 'true'
    xml_dict['flow-definition']['description'] = desc
    result = xmltodict.unparse(
        xml_dict, short_empty_elements=True, pretty=True)
    return result
