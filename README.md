## Purpose

To pull EBS IO and Throughput metrics from Cloudwatch. This will help estimate costs for workloads that may move to a service with IO charges (e.g. AWS Aurora). The get-ebs-metrics.py script takes a CSV that has a region and EBS ID column. 

## Setup and Usage

**Training**
- install libraries 
  ```py
  pip install -r requirements.txt
  ```
- specify days back from current
  ```py
  python get-ebs-metrics.py 
  ```
- specify days back to pull CloudWatch data
  ```py
  python get-ebs-metrics.py -d 14
  ``` 


_For more examples, please refer to the [Documentation](https://somerepo.com)_

<p align="right">(<a href="#readme-top">back to top</a>)</p>


## Roadmap

- [ ] Add ability to automatically calculate $ value of Aurora IO usage

See the [open issues](https://somerepo.com) for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>


## Contributing

Contributions are what make the open source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement". Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/UsefulFeature`)
3. Commit your Changes (`git commit -m 'Add some UsefulFeature'`)
4. Push to the Branch (`git push origin feature/UsefulFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>


## Contact

Eric Garcia - grmeri@amazon.com

Project Link: [https://somerepo.com](https://somerepo.com)



