# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
def generate_html_response(apihost,whisk_user,github_user):
    """
    Builds simple HTML page to provide feedback to a user
    """

    return f"""
<html>
    <body style='background-color:#1da1ce;'>
        <div style='width: 100%;background-color: #1da1ce;justify-content: flex-start;display: flex;'>                            
            <a href='https://nuvolaris.io' aria-current="page" aria-label='home'>
                <img src='https://assets-global.website-files.com/64b64691257b91236b0e7482/64bfcab6bd343008e30e5d06_Nuvolaris%20logo%20white.png' loading='lazy' width='195' alt='Nuvolaris Logo.'>
            </a>                
        </div>
        <div style='width: 100%;height: 50rem;max-width: 100%;background-color: #1da1ce;flex-direction: column;margin-left: 0;margin-right: 0;display: flex;'>
            <h1 style='color: #fff;text-align: left;font-family: Work Sans, sans-serif;font-size: 1.75rem;font-weight: 600;'>Congratulations, you have successfully configured a free <strong>nuvolaris</strong> account on domain {apihost}</h1>
            <p style='color: #fff;text-align: left;font-family: Work Sans, sans-serif;font-size: 1rem;font-weight: 400;'>Please take note of your account details as you won't be able to access this page again!</p>           
            <div style='background-color: #fff;flex-direction: column;padding-left: 10px;paddiing-right: 10px;display: flex; color: #000;'>
                <ul>
                    <li>account name: <strong>{github_user['login']}</strong></li>
                    <li>account email: <strong>{github_user['email']}</strong></li>
                    <li>account password: <strong>{whisk_user['spec']['password']}</strong></li>
                </ul>
                <p>
                   You have a dedicated web space available at the URL: <strong><a href='https://{github_user['login']}.{apihost}' target='_blank'>https://{github_user['login']}.{apihost}</a></strong>
                </p>
                <p>
                   To login to your free account via nuv CLI executes in a shell the command <br/><br/> <strong>nuv -login https://{apihost} {github_user['login']}</strong> entering the provided password at the prompt
                </p>
            </div>
        </div> 
    </body>
</html>
"""

def generate_html_error(apihost,message):
    """
    Builds simple HTML page to provide feedback to a user
    """

    return f"""
<html>
    <body style='background-color:#1da1ce;'>
        <div style='width: 100%;background-color: #1da1ce;justify-content: flex-start;display: flex;'>                            
            <a href='https://nuvolaris.io' aria-current="page" aria-label='home'>
                <img src='https://assets-global.website-files.com/64b64691257b91236b0e7482/64bfcab6bd343008e30e5d06_Nuvolaris%20logo%20white.png' loading='lazy' width='195' alt='Nuvolaris Logo.'>
            </a>                
        </div>
        <div style='width: 100%;height: 50rem;max-width: 100%;background-color: #1da1ce;flex-direction: column;margin-left: 0;margin-right: 0;display: flex;'>
            <h1 style='color: #fff;text-align: left;font-family: Work Sans, sans-serif;font-size: 1.75rem;font-weight: 600;'>Oops, something went wront setting a <strong>nuvolaris</strong> account on domain {apihost}</h1>
            <p style='color: #fff;text-align: left;font-family: Work Sans, sans-serif;font-size: 1rem;font-weight: 400;'>Please take a look at the provided error description</p>           
            <div style='background-color: #fff;flex-direction: column;padding-left: 10px;paddiing-right: 10px;display: flex; color: #000;'>                
                <p>
                   {message}
                </p>
            </div>
        </div> 
    </body>
</html>
"""