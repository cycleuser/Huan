# ![CycleUser](./theme/image/default-logo.png) GeoPyTool

🌙

  * [Homepage](http://geopytool.com)
  * [WebVersion](http://geopytool.com/GeoJsTool.html)
  * [Forum](https://github.com/GeoPyTool/GeoPyTool/issues)
  * [加入QQ群](http://geopytool.com/zhong-wen-jian-jie.html)
  * [Installation](http://geopytool.com/installation-expert.html)
  * [Templates](https://github.com/GeoPyTool/GeoPyTool/tree/master/DataFileSamples)
  * [Demo](http://geopytool.com/demonstration.html)
  * [Github](https://github.com/GeoPyTool/GeoPyTool)
  * [Archives](http://geopytool.com/archives.html)



[Blog](.) ›[English](category/english.html) ›Installation-Expert 

## Installation-Expert

Post in [周四 31 十二月 2020 ](./archive/2020/12月/index.html) |Tags [Doc](./tag/doc.html) [English](./tag/english.html) [Support](./tag/support.html)

# Installation, For Expert

GeoPyTool can also be used as a module inside Python.

# 1\. Install Python

Find help from [Python official website](https://www.python.org/downloads/) please.

# 2\. Install Needed Modules

Then run the following commands in **terminal** to install some base modules:
    
    
    pip install cython numpy scipy matplotlib sympy pandas xlrd pyopengl BeautifulSoup4 pyqt5 scikit-learn requests tensorflow torch keras tqdm gym DRL
    

If you encounter errors, which might be related to numpy or tensorflow, please run the following commands to specify a particular version.
    
    
    pip install numpy ==1.8.5
    pip install tensorflow==2.3.1
    

# 3\. Install GeoPyTool

After all the modules above getting installed, run the following command to install GeoPyTool:
    
    
    pip install geopytool
    

If there comes no error message, everything should have been done successfully.

# 4\. Run GeoPyTool

If there is no error reported, run the following commands in the Terminal to run GeoPyTool:
    
    
    python -c "import geopytool;geopytool.main()"
    

# 5\. Update an existing GeoPyTool

If you installed GeoPyTool as a module in Python, you can use the following command in the **terminal** to update GeoPyTool to the latest version on any operating system:
    
    
    pip install geopytool --update --no-cache-dir
    

It is a good idea to update **GeoPyTool** with pip everytime before you use it.

Category: [English](./category/english.html)

Category 

  * [Chinese](./category/chinese.html)
  * [Doc](./category/doc.html)
  * [English](./category/english.html)



Tagcloud 

[中文](./tag/zhong-wen.html) [English](./tag/english.html) [Chinese](./tag/chinese.html) [Support](./tag/support.html) [Doc](./tag/doc.html) [文档](./tag/wen-dang.html)

Links 

  * [Introduction](http://geopytool.com/introduction.html)
  * [Functions](http://geopytool.com/functions.html)
  * [Installation](http://geopytool.com/installation-expert.html)
  * [Demonstration](http://geopytool.com/demonstration.html)
  * [Download](http://geopytool.com/download.html)
  * [中文简介](http://geopytool.com/zhong-wen-jian-jie.html)
  * [功能列表](http://geopytool.com/gong-neng-lie-biao.html)
  * [安装指南](http://geopytool.com/an-zhuang-zhi-nan-jin-jie.html)
  * [功能演示](http://geopytool.com/yan-shi-shi-pin.html)
  * [下载链接](http://geopytool.com/download.html)






[ ![知识共享许可协议](https://i.creativecommons.org/l/by-nc-sa/3.0/88x31.png) ](https://creativecommons.org/licenses/by-nc-sa/3.0/)

Powered by [Pelican](https://getpelican.com/)   
which takes great advantage of [Python](https://python.org)
  *[
[周四 31 十二月 2020 ](./archive/2020/12月/index.html)
]: 2020-12-31T19:13:50+08:00